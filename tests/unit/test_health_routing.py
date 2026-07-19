"""Tests for health tracking, quota-aware routing, and BestFreePolicy."""

from llm_kernel.core import (
    Message,
    Request,
    Role,
    UsageRecord,
)
from llm_kernel.planner import (
    BestFreePolicy,
    HealthSnapshot,
    ModelMetadata,
    Planner,
    PlanningError,
    ProviderMetadata,
    QuotaSnapshot,
    WorldState,
    resolve_policy,
)
from llm_kernel.runtime import HealthTracker


def _make_provider(
    name: str = "groq",
    daily_limit: int | None = 1000,
    quality: float = 0.8,
    latency: float = 0.95,
) -> ProviderMetadata:
    return ProviderMetadata(
        name=name,
        display_name=name.title(),
        adapter_type="openai",
        base_url=f"https://api.{name}.com/v1",
        api_key_env=f"{name.upper()}_API_KEY",
        models=[
            ModelMetadata(
                id=f"{name}-model",
                display_name=f"{name} Model",
                max_context_tokens=131_072,
                quality_score=quality,
                latency_score=latency,
            ),
        ],
        default_model=f"{name}-model",
        daily_request_limit=daily_limit,
    )


class TestHealthTracker:
    def test_record_success_updates_health_and_latency(self):
        tracker = HealthTracker()
        tracker.record_success("groq", 150.0)
        tracker.record_success("groq", 250.0)

        health = tracker.get_health()
        assert health.is_healthy("groq")

        quota = tracker.get_quota()
        assert quota.get_latency("groq") == 200.0  # avg of 150 + 250

    def test_record_failure_degrades_health(self):
        tracker = HealthTracker()
        tracker.record_failure("groq", "server")
        tracker.record_failure("groq", "server")

        health = tracker.get_health()
        assert health.status.get("groq") == "degraded"

    def test_three_failures_mark_unhealthy(self):
        tracker = HealthTracker()
        for _ in range(3):
            tracker.record_failure("groq", "server")

        health = tracker.get_health()
        assert not health.is_available("groq")
        assert health.status.get("groq") == "unhealthy"

    def test_rate_limit_immediately_degrades(self):
        tracker = HealthTracker()
        tracker.record_failure("groq", "rate_limit")

        health = tracker.get_health()
        assert health.status.get("groq") == "degraded"

    def test_success_recovers_from_degraded(self):
        tracker = HealthTracker()
        tracker.record_failure("groq", "server")
        tracker.record_failure("groq", "server")
        assert tracker.get_health().status.get("groq") == "degraded"

        tracker.record_success("groq", 100.0)
        assert tracker.get_health().status.get("groq") == "healthy"

    def test_success_recovers_from_unhealthy_to_degraded(self):
        tracker = HealthTracker()
        for _ in range(3):
            tracker.record_failure("groq", "server")
        assert tracker.get_health().status.get("groq") == "unhealthy"

        tracker.record_success("groq", 100.0)
        assert tracker.get_health().status.get("groq") == "degraded"

    def test_quota_remaining_with_limit(self):
        tracker = HealthTracker(daily_limits={"groq": 100})
        for _ in range(30):
            tracker.record_success("groq", 100.0)

        assert tracker.quota_remaining("groq") == 0.7

    def test_quota_remaining_without_limit(self):
        tracker = HealthTracker()
        tracker.record_success("groq", 100.0)

        assert tracker.quota_remaining("groq") == 1.0

    def test_quota_remaining_exhausted(self):
        tracker = HealthTracker(daily_limits={"groq": 10})
        for _ in range(10):
            tracker.record_success("groq", 100.0)

        assert tracker.quota_remaining("groq") == 0.0

    def test_is_available_default_healthy(self):
        tracker = HealthTracker()
        assert tracker.is_available("unknown_provider")


class TestBestFreePolicy:
    def test_healthy_provider_scores_higher_than_degraded(self):
        provider = _make_provider()
        policy = BestFreePolicy()

        healthy = HealthSnapshot({"groq": "healthy"})
        degraded = HealthSnapshot({"groq": "degraded"})

        request = Request(messages=[Message(role=Role.USER, content="hi")])
        quota = QuotaSnapshot()

        score_healthy = policy.score(request, provider, provider.models[0], 10, healthy, quota)
        score_degraded = policy.score(request, provider, provider.models[0], 10, degraded, quota)

        assert score_healthy > score_degraded

    def test_unhealthy_provider_returns_negative(self):
        provider = _make_provider()
        policy = BestFreePolicy()

        health = HealthSnapshot({"groq": "unhealthy"})
        request = Request(messages=[Message(role=Role.USER, content="hi")])
        quota = QuotaSnapshot()

        score = policy.score(request, provider, provider.models[0], 10, health, quota)
        assert score == -1.0

    def test_provider_with_more_quota_remaining_scores_higher(self):
        provider = _make_provider(daily_limit=100)
        policy = BestFreePolicy()

        health = HealthSnapshot({"groq": "healthy"})
        request = Request(messages=[Message(role=Role.USER, content="hi")])

        quota_full = QuotaSnapshot()
        quota_used = QuotaSnapshot(
            usage={"groq": UsageRecord(
                provider="groq", model="groq-model", day="2026-01-01",
                request_count=90,
            )},
        )

        score_full = policy.score(request, provider, provider.models[0], 10, health, quota_full)
        score_used = policy.score(request, provider, provider.models[0], 10, health, quota_used)

        assert score_full > score_used

    def test_model_match_overrides_everything(self):
        provider = _make_provider()
        policy = BestFreePolicy()

        health = HealthSnapshot({"groq": "degraded"})
        request = Request(
            messages=[Message(role=Role.USER, content="hi")],
            model="groq-model",
        )
        quota = QuotaSnapshot()

        score = policy.score(request, provider, provider.models[0], 10, health, quota)
        # Model match adds 100.0, so even degraded provider gets a high score
        assert score > 100.0


class TestPlannerWithHealthAndQuota:
    def test_planner_skips_unhealthy_provider(self):
        groq = _make_provider("groq")
        google = _make_provider("google", quality=0.7, latency=0.8)

        ws = WorldState(
            providers=[groq, google],
            health={"groq": "unhealthy"},
        )
        planner = Planner(ws, policy=BestFreePolicy())
        request = Request(messages=[Message(role=Role.USER, content="hi")])
        plan = planner.plan(request)

        # groq should be last (score -1.0) or filtered out
        assert plan.candidates[0].provider == "google"

    def test_planner_prefers_provider_with_more_quota(self):
        groq = _make_provider("groq", daily_limit=100, quality=0.8)
        google = _make_provider("google", daily_limit=1000, quality=0.75)

        ws = WorldState(
            providers=[groq, google],
            usage={
                "groq": UsageRecord(
                    provider="groq", model="groq-model", day="2026-01-01",
                    request_count=95,  # 95% used
                ),
            },
        )
        planner = Planner(ws, policy=BestFreePolicy())
        request = Request(messages=[Message(role=Role.USER, content="hi")])
        plan = planner.plan(request)

        # google has more quota remaining, should rank first despite lower quality
        assert plan.candidates[0].provider == "google"

    def test_planner_with_health_tracker_integration(self):
        groq = _make_provider("groq")
        google = _make_provider("google", quality=0.7, latency=0.8)

        tracker = HealthTracker(daily_limits={"groq": 1000, "google": 1500})
        # Simulate groq going down
        for _ in range(3):
            tracker.record_failure("groq", "server")

        ws = WorldState(
            providers=[groq, google],
            health=dict(tracker.get_health().status),
        )
        planner = Planner(ws, policy=BestFreePolicy())
        request = Request(messages=[Message(role=Role.USER, content="hi")])
        plan = planner.plan(request)

        assert plan.candidates[0].provider == "google"
        assert not tracker.is_available("groq")


class TestPerRequestPolicy:
    def test_plan_accepts_policy_string_override(self):
        groq = _make_provider("groq", quality=0.9, latency=0.95)
        google = _make_provider("google", quality=0.7, latency=0.8)

        ws = WorldState(providers=[groq, google])
        planner = Planner(ws)  # default policy
        request = Request(messages=[Message(role=Role.USER, content="hi")])

        # With "quality" policy, groq (0.9) should beat google (0.7)
        plan_quality = planner.plan(request, policy="quality")
        assert plan_quality.candidates[0].provider == "groq"

        # With "fastest" policy, groq (0.95) should still beat google (0.8)
        plan_fastest = planner.plan(request, policy="fastest")
        assert plan_fastest.candidates[0].provider == "groq"

    def test_plan_accepts_policy_instance_override(self):
        groq = _make_provider("groq", quality=0.9, latency=0.95)
        google = _make_provider("google", quality=0.7, latency=0.8)

        ws = WorldState(providers=[groq, google])
        planner = Planner(ws, policy=BestFreePolicy())
        request = Request(messages=[Message(role=Role.USER, content="hi")])

        # Override with a different policy instance
        from llm_kernel.planner import FastestPolicy
        plan = planner.plan(request, policy=FastestPolicy())
        # FastestPolicy scores by latency_score: groq (0.95) > google (0.8)
        assert plan.candidates[0].provider == "groq"

    def test_unknown_policy_name_raises(self):
        groq = _make_provider("groq")
        ws = WorldState(providers=[groq])
        planner = Planner(ws)
        request = Request(messages=[Message(role=Role.USER, content="hi")])

        try:
            planner.plan(request, policy="nonexistent")
            raise AssertionError("Should have raised PlanningError")
        except PlanningError:
            pass

    def test_default_policy_used_when_none(self):
        groq = _make_provider("groq")
        ws = WorldState(providers=[groq])
        planner = Planner(ws, policy=BestFreePolicy())
        request = Request(messages=[Message(role=Role.USER, content="hi")])

        # No override → uses planner's default (BestFreePolicy)
        plan = planner.plan(request)
        assert len(plan.candidates) == 1
        assert plan.candidates[0].provider == "groq"


class TestResolvePolicy:
    def test_resolve_by_name(self):
        policy = resolve_policy("best_free")
        assert isinstance(policy, BestFreePolicy)

    def test_resolve_none_returns_default(self):
        from llm_kernel.planner import DefaultRoutingPolicy
        policy = resolve_policy(None)
        assert isinstance(policy, DefaultRoutingPolicy)

    def test_resolve_instance_passthrough(self):
        custom = BestFreePolicy()
        assert resolve_policy(custom) is custom

    def test_resolve_unknown_raises(self):
        try:
            resolve_policy("nonsense")
            raise AssertionError("Should have raised")
        except PlanningError:
            pass


class TestProviderHealth:
    def test_provider_health_returns_all_providers(self):
        from llm_kernel.client import LLMClient

        groq = _make_provider("groq", daily_limit=100)
        google = _make_provider("google", daily_limit=200)

        ws = WorldState(providers=[groq, google])
        client = LLMClient(
            providers=[groq, google],
            world_state=ws,
            adapters={},
        )

        health = client.provider_health()
        assert "groq" in health
        assert "google" in health
        assert health["groq"]["status"] == "healthy"
        assert health["groq"]["daily_limit"] == 100
        assert health["google"]["daily_limit"] == 200

    def test_provider_health_reflects_failures(self):
        from llm_kernel.client import LLMClient

        groq = _make_provider("groq", daily_limit=100)

        ws = WorldState(providers=[groq])
        client = LLMClient(
            providers=[groq],
            world_state=ws,
            adapters={},
        )

        # Simulate failures
        for _ in range(3):
            client._health_tracker.record_failure("groq", "server")

        health = client.provider_health()
        assert health["groq"]["status"] == "unhealthy"
        assert health["groq"]["quota_remaining"] == 1.0  # no successes recorded

    def test_provider_health_reflects_quota_usage(self):
        from llm_kernel.client import LLMClient

        groq = _make_provider("groq", daily_limit=100)

        ws = WorldState(providers=[groq])
        client = LLMClient(
            providers=[groq],
            world_state=ws,
            adapters={},
        )

        # Simulate 50 successful requests
        for _ in range(50):
            client._health_tracker.record_success("groq", 150.0)

        health = client.provider_health()
        assert health["groq"]["status"] == "healthy"
        assert health["groq"]["requests_today"] == 50
        assert health["groq"]["quota_remaining"] == 0.5
        assert health["groq"]["latency_ms"] == 150.0
