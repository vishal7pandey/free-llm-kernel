"""Tests for routing policies and state views.

Covers the architectural split between 'what can execute' (Planner)
and 'what should execute' (RoutingPolicy).
"""

import pytest

from llm_kernel.core import (
    Capability,
    Message,
    Request,
    Role,
    UsageRecord,
)
from llm_kernel.planner import (
    CheapestPolicy,
    DefaultRoutingPolicy,
    FastestPolicy,
    HealthSnapshot,
    Planner,
    ProviderCatalogue,
    ProviderMetadata,
    ModelMetadata,
    QualityPolicy,
    QuotaSnapshot,
    RoutingPolicy,
    WorldState,
)


@pytest.fixture
def sample_provider():
    return ProviderMetadata(
        name="groq",
        display_name="Groq",
        adapter_type="openai",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        models=[
            ModelMetadata(
                id="llama-3.3-70b",
                display_name="Llama 3.3 70B",
                max_context_tokens=131_072,
                quality_score=0.8,
                latency_score=0.95,
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
            ),
            ModelMetadata(
                id="llama-3.1-8b",
                display_name="Llama 3.1 8B",
                max_context_tokens=131_072,
                quality_score=0.6,
                latency_score=0.98,
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
            ),
        ],
        default_model="llama-3.3-70b",
    )


@pytest.fixture
def sample_request():
    return Request(messages=[Message(role=Role.USER, content="Hello!")])


@pytest.fixture
def empty_health():
    return HealthSnapshot()


@pytest.fixture
def empty_quota():
    return QuotaSnapshot()


class TestProviderCatalogue:
    def test_get_existing(self, sample_provider):
        cat = ProviderCatalogue([sample_provider])
        assert cat.get("groq") is sample_provider

    def test_get_missing_returns_none(self, sample_provider):
        cat = ProviderCatalogue([sample_provider])
        assert cat.get("openai") is None

    def test_names(self, sample_provider):
        cat = ProviderCatalogue([sample_provider])
        assert cat.names() == ["groq"]


class TestHealthSnapshot:
    def test_default_healthy(self):
        health = HealthSnapshot()
        assert health.is_healthy("groq") is True
        assert health.is_available("groq") is True

    def test_unhealthy(self):
        health = HealthSnapshot(status={"groq": "unhealthy"})
        assert health.is_healthy("groq") is False
        assert health.is_available("groq") is False

    def test_degraded_still_available(self):
        health = HealthSnapshot(status={"groq": "degraded"})
        assert health.is_healthy("groq") is False
        assert health.is_available("groq") is True


class TestQuotaSnapshot:
    def test_get_usage_none(self):
        quota = QuotaSnapshot()
        assert quota.get_usage("groq") is None

    def test_get_usage_existing(self):
        record = UsageRecord(
            provider="groq", model="llama-3.3-70b", day="2026-01-01",
            request_count=5, prompt_tokens=100, completion_tokens=50,
        )
        quota = QuotaSnapshot(usage={"groq": record})
        assert quota.get_usage("groq") is record

    def test_get_latency_none(self):
        quota = QuotaSnapshot()
        assert quota.get_latency("groq") is None

    def test_get_latency_existing(self):
        quota = QuotaSnapshot(latency={"groq": 250.0})
        assert quota.get_latency("groq") == 250.0


class TestWorldStateViews:
    def test_catalogue_property(self, sample_provider):
        ws = WorldState(providers=[sample_provider])
        assert isinstance(ws.catalogue, ProviderCatalogue)
        assert ws.catalogue.get("groq") is sample_provider

    def test_health_snapshot_property(self, sample_provider):
        ws = WorldState(providers=[sample_provider], health={"groq": "unhealthy"})
        assert isinstance(ws.health_snapshot, HealthSnapshot)
        assert ws.health_snapshot.is_available("groq") is False

    def test_quota_snapshot_property(self, sample_provider):
        ws = WorldState(providers=[sample_provider], latency={"groq": 300.0})
        assert isinstance(ws.quota_snapshot, QuotaSnapshot)
        assert ws.quota_snapshot.get_latency("groq") == 300.0


class TestDefaultRoutingPolicy:
    def test_scores_higher_for_better_quality(
        self, sample_provider, sample_request, empty_health, empty_quota
    ):
        policy = DefaultRoutingPolicy()
        model_70b = sample_provider.models[0]
        model_8b = sample_provider.models[1]
        score_70b = policy.score(sample_request, sample_provider, model_70b, 10, empty_health, empty_quota)
        score_8b = policy.score(sample_request, sample_provider, model_8b, 10, empty_health, empty_quota)
        assert score_70b > score_8b

    def test_user_model_match_gets_bonus(
        self, sample_provider, empty_health, empty_quota
    ):
        policy = DefaultRoutingPolicy()
        model = sample_provider.models[0]
        req_with_model = Request(
            messages=[Message(role=Role.USER, content="Hi")],
            model="llama-3.3-70b",
        )
        req_without = Request(messages=[Message(role=Role.USER, content="Hi")])
        score_with = policy.score(req_with_model, sample_provider, model, 10, empty_health, empty_quota)
        score_without = policy.score(req_without, sample_provider, model, 10, empty_health, empty_quota)
        assert score_with > score_without + 50  # Large bonus


class TestFastestPolicy:
    def test_prefers_higher_latency_score(
        self, sample_provider, sample_request, empty_health, empty_quota
    ):
        policy = FastestPolicy()
        model_70b = sample_provider.models[0]  # latency_score=0.95
        model_8b = sample_provider.models[1]   # latency_score=0.98
        score_70b = policy.score(sample_request, sample_provider, model_70b, 10, empty_health, empty_quota)
        score_8b = policy.score(sample_request, sample_provider, model_8b, 10, empty_health, empty_quota)
        assert score_8b > score_70b


class TestCheapestPolicy:
    def test_prefers_lower_cost(self, sample_request, empty_health, empty_quota):
        provider = ProviderMetadata(
            name="test",
            display_name="Test",
            adapter_type="openai",
            base_url="https://api.test.com/v1",
            api_key_env="TEST_KEY",
            models=[
                ModelMetadata(id="cheap", display_name="Cheap", max_context_tokens=4096,
                              cost_per_1k_input=0.0, cost_per_1k_output=0.0),
                ModelMetadata(id="expensive", display_name="Expensive", max_context_tokens=4096,
                              cost_per_1k_input=0.01, cost_per_1k_output=0.02),
            ],
            default_model="cheap",
        )
        policy = CheapestPolicy()
        cheap = provider.models[0]
        expensive = provider.models[1]
        score_cheap = policy.score(sample_request, provider, cheap, 10, empty_health, empty_quota)
        score_expensive = policy.score(sample_request, provider, expensive, 10, empty_health, empty_quota)
        assert score_cheap > score_expensive


class TestQualityPolicy:
    def test_prefers_higher_quality(self, sample_provider, sample_request, empty_health, empty_quota):
        policy = QualityPolicy()
        model_70b = sample_provider.models[0]  # quality_score=0.8
        model_8b = sample_provider.models[1]   # quality_score=0.6
        score_70b = policy.score(sample_request, sample_provider, model_70b, 10, empty_health, empty_quota)
        score_8b = policy.score(sample_request, sample_provider, model_8b, 10, empty_health, empty_quota)
        assert score_70b > score_8b


class TestPlannerWithPolicy:
    def test_planner_accepts_custom_policy(self, sample_provider):
        ws = WorldState(providers=[sample_provider])
        planner = Planner(world_state=ws, policy=FastestPolicy())
        request = Request(messages=[Message(role=Role.USER, content="Hi")])
        plan = planner.plan(request)
        # FastestPolicy should prefer 8b (latency_score=0.98) over 70b (0.95)
        assert plan.candidates[0].model == "llama-3.1-8b"

    def test_planner_with_quality_policy(self, sample_provider):
        ws = WorldState(providers=[sample_provider])
        planner = Planner(world_state=ws, policy=QualityPolicy())
        request = Request(messages=[Message(role=Role.USER, content="Hi")])
        plan = planner.plan(request)
        # QualityPolicy should prefer 70b (quality_score=0.8) over 8b (0.6)
        assert plan.candidates[0].model == "llama-3.3-70b"

    def test_planner_filters_unhealthy_provider(self, sample_provider):
        ws = WorldState(
            providers=[sample_provider],
            health={"groq": "unhealthy"},
        )
        planner = Planner(world_state=ws)
        request = Request(messages=[Message(role=Role.USER, content="Hi")])
        with pytest.raises(Exception):
            planner.plan(request)

    def test_routing_policy_is_protocol(self):
        assert hasattr(RoutingPolicy, "score")
