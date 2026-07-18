"""Tests for llm_kernel.planner — specification-driven, TDD style.

These tests are derived from INTERFACE.md, ARCHITECTURE.md, and DVM.md.
Run: uv run pytest tests/unit/planner -v
"""

import pytest


class TestWorldState:
    def test_world_state_creation(self):
        from llm_kernel.planner import WorldState, ProviderMetadata, ModelMetadata

        provider = ProviderMetadata(
            name="groq",
            display_name="Groq",
            adapter_type="openai",
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY",
            models=[ModelMetadata(id="llama-3.3-70b", display_name="Llama 3.3 70B", max_context_tokens=128000)],
            default_model="llama-3.3-70b",
        )

        ws = WorldState(providers=[provider])
        assert len(ws.providers) == 1
        assert ws.providers[0].name == "groq"


class TestPlannerPlan:
    @pytest.fixture
    def sample_providers(self):
        from llm_kernel.planner import ProviderMetadata, ModelMetadata
        from llm_kernel.core import Capability

        return [
            ProviderMetadata(
                name="groq",
                display_name="Groq",
                adapter_type="openai",
                base_url="https://api.groq.com/openai/v1",
                api_key_env="GROQ_API_KEY",
                models=[
                    ModelMetadata(
                        id="llama-3.3-70b",
                        display_name="Llama 3.3 70B",
                        max_context_tokens=128000,
                        capabilities={Capability.STREAMING, Capability.TOOLS},
                        quality_score=0.9,
                        latency_score=0.95,
                    )
                ],
                default_model="llama-3.3-70b",
                priority=1,
            ),
            ProviderMetadata(
                name="google",
                display_name="Google AI Studio",
                adapter_type="openai",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                api_key_env="GOOGLE_API_KEY",
                models=[
                    ModelMetadata(
                        id="gemini-2.0-flash",
                        display_name="Gemini 2.0 Flash",
                        max_context_tokens=1000000,
                        capabilities={Capability.STREAMING, Capability.VISION, Capability.JSON_MODE},
                        quality_score=0.85,
                        latency_score=0.8,
                    )
                ],
                default_model="gemini-2.0-flash",
                priority=2,
            ),
            ProviderMetadata(
                name="cloudflare",
                display_name="Cloudflare Workers AI",
                adapter_type="openai",
                base_url="https://api.cloudflare.com/...",
                api_key_env="CLOUDFLARE_API_TOKEN",
                models=[
                    ModelMetadata(
                        id="llama-3.2-8b",
                        display_name="Llama 3.2 8B",
                        max_context_tokens=8192,
                        capabilities={Capability.STREAMING},
                        quality_score=0.6,
                        latency_score=0.9,
                    )
                ],
                default_model="llama-3.2-8b",
                priority=3,
            ),
        ]

    @pytest.fixture
    def planner(self, sample_providers):
        from llm_kernel.planner import Planner, WorldState

        ws = WorldState(providers=sample_providers)
        return Planner(world_state=ws)

    def test_plan_returns_execution_plan(self, planner):
        from llm_kernel.core import Request, Message, Role

        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        plan = planner.plan(request)

        assert plan.candidates
        assert plan.trace_id == request.trace_id

    def test_plan_selects_highest_scoring_provider_first(self, planner):
        from llm_kernel.core import Request, Message, Role

        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        plan = planner.plan(request)

        # Groq has the highest quality+latency, so it should rank first
        assert plan.candidates[0].provider == "groq"
        assert plan.candidates[0].model == "llama-3.3-70b"

    def test_plan_filters_by_capability(self, planner):
        from llm_kernel.core import Request, Message, Role, Capability

        request = Request(
            messages=[Message(role=Role.USER, content="Use a tool")],
            capabilities_required={Capability.TOOLS},
        )
        plan = planner.plan(request)

        provider_names = {c.provider for c in plan.candidates}
        assert "groq" in provider_names
        # Google model in fixture doesn't support TOOLS
        assert "google" not in provider_names

    def test_plan_filters_by_context_window(self, planner):
        from llm_kernel.core import Request, Message, Role

        # Long prompt that exceeds 8k context (8k tokens * 4 chars/token = 32k chars)
        long_text = "word " * 7000  # ~35k characters, estimated tokens > 8k
        request = Request(messages=[Message(role=Role.USER, content=long_text)])
        plan = planner.plan(request)

        provider_names = {c.provider for c in plan.candidates}
        assert "cloudflare" not in provider_names
        assert "groq" in provider_names or "google" in provider_names

    def test_plan_raises_planning_error_when_no_provider_matches(self, planner):
        from llm_kernel.core import (
            Request,
            Message,
            Role,
            Capability,
        )
        from llm_kernel.planner import PlanningError

        request = Request(
            messages=[Message(role=Role.USER, content="Hello")],
            capabilities_required={Capability.REASONING},  # No provider has this
        )

        with pytest.raises(PlanningError):
            planner.plan(request)

    def test_plan_candidates_sorted_by_score_descending(self, planner):
        from llm_kernel.core import Request, Message, Role

        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        plan = planner.plan(request)

        scores = [c.score for c in plan.candidates]
        assert scores == sorted(scores, reverse=True)

    def test_plan_no_duplicate_candidates(self, planner):
        from llm_kernel.core import Request, Message, Role

        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        plan = planner.plan(request)

        keys = [(c.provider, c.model) for c in plan.candidates]
        assert len(keys) == len(set(keys))

    def test_plan_respects_user_forced_model(self, planner):
        from llm_kernel.core import Request, Message, Role

        request = Request(
            messages=[Message(role=Role.USER, content="Hello!")],
            model="gemini-2.0-flash",
        )
        plan = planner.plan(request)

        assert plan.candidates[0].provider == "google"
        assert plan.candidates[0].model == "gemini-2.0-flash"

    def test_plan_deterministic(self, planner):
        from llm_kernel.core import Request, Message, Role

        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        plan1 = planner.plan(request)
        plan2 = planner.plan(request)

        assert plan1 == plan2

    def test_plan_does_not_mutate_request(self, planner):
        from llm_kernel.core import Request, Message, Role

        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        original = request
        planner.plan(request)

        assert request is original
        assert request == original


class TestTokenEstimator:
    def test_default_estimator_returns_positive_count(self):
        from llm_kernel.planner import DefaultTokenEstimator

        estimator = DefaultTokenEstimator()
        count = estimator.estimate("Hello world!")
        assert count > 0

    def test_default_estimator_scales_with_length(self):
        from llm_kernel.planner import DefaultTokenEstimator

        estimator = DefaultTokenEstimator()
        short_count = estimator.estimate("Hello")
        long_count = estimator.estimate("Hello " * 100)

        assert long_count > short_count
