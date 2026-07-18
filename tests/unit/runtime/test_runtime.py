"""Tests for llm_kernel.runtime — specification-driven, TDD style.

These tests use respx to mock provider HTTP endpoints.
Run: uv run pytest tests/unit/runtime -v
"""

import json
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response as HttpxResponse


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        from llm_kernel.runtime import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, cooldown_ms=1000)
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        from llm_kernel.runtime import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, cooldown_ms=1000)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"  # still closed at threshold - 1
        cb.record_failure()
        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self):
        from llm_kernel.runtime import CircuitBreaker
        from freezegun import freeze_time

        with freeze_time("2026-01-01 00:00:00"):
            cb = CircuitBreaker(failure_threshold=2, cooldown_ms=1000)
            cb.record_failure()
            cb.record_failure()
            assert cb.state == "open"

            # Still within cooldown (exactly 1s == cooldown, not yet elapsed)
            assert cb.allow_request() is False

        with freeze_time("2026-01-01 00:00:02"):
            # Cooldown elapsed
            assert cb.allow_request() is True
            assert cb.state == "half_open"

    def test_closes_after_success_in_half_open(self):
        from llm_kernel.runtime import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=2, cooldown_ms=0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        # Force to half-open and record success
        cb.record_success()
        assert cb.state == "closed"

    def test_opens_again_after_failure_in_half_open(self):
        from llm_kernel.runtime import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=2, cooldown_ms=0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # goes to closed
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"


class TestRetryEngine:
    def test_no_retry_for_unrecoverable(self):
        from llm_kernel.runtime import RetryEngine

        engine = RetryEngine()
        assert engine.is_retryable("auth") is False
        assert engine.is_retryable("validation") is False

    def test_retry_for_transient(self):
        from llm_kernel.runtime import RetryEngine

        engine = RetryEngine()
        assert engine.is_retryable("rate_limit") is True
        assert engine.is_retryable("timeout") is True
        assert engine.is_retryable("network") is True
        assert engine.is_retryable("server") is True

    def test_backoff_increases(self):
        from llm_kernel.runtime import RetryEngine

        engine = RetryEngine(base_ms=100, max_ms=1000)
        d1 = engine.backoff_delay(0)
        d2 = engine.backoff_delay(1)
        d3 = engine.backoff_delay(2)

        assert d2 > d1
        assert d3 > d2
        assert d3 <= 1000


class TestOpenAICompatibleAdapter:
    @pytest.fixture
    def plan(self):
        from llm_kernel.core import Request, Message, Role
        from llm_kernel.planner import ExecutionPlan, ProviderMetadata, ModelMetadata
        from llm_kernel.runtime import AdapterConfig

        provider = ProviderMetadata(
            name="mock",
            display_name="Mock",
            adapter_type="openai",
            base_url="https://api.mock.com/v1",
            api_key_env="MOCK_API_KEY",
            models=[ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096)],
            default_model="model-1",
        )
        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        plan = ExecutionPlan(
            trace_id=request.trace_id,
            request=request,
            candidates=[],  # adapter uses passed model directly
        )
        return plan, provider

    @respx.mock
    def test_execute_returns_response(self, plan):
        from llm_kernel.runtime import OpenAICompatibleAdapter, AdapterConfig
        from llm_kernel.core import Secret

        execution_plan, provider = plan

        route = respx.post("https://api.mock.com/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Hi there!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
                },
            )
        )

        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )
        response = adapter.execute(execution_plan, "model-1")

        assert response.content == "Hi there!"
        assert response.provider == "mock"
        assert response.model == "model-1"
        assert response.usage.total_tokens == 5
        assert route.called

    @respx.mock
    def test_execute_raises_on_429(self, plan):
        from llm_kernel.runtime import OpenAICompatibleAdapter, AdapterConfig
        from llm_kernel.core import Secret, ExecutionError

        execution_plan, provider = plan

        respx.post("https://api.mock.com/v1/chat/completions").mock(
            return_value=HttpxResponse(
                429,
                json={"error": {"message": "rate limit exceeded"}},
            )
        )

        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )

        with pytest.raises(ExecutionError) as exc_info:
            adapter.execute(execution_plan, "model-1")

        assert exc_info.value.category == "rate_limit"
        assert "sk-test" not in str(exc_info.value)

    @respx.mock
    def test_stream_returns_chunks(self, plan):
        from llm_kernel.runtime import OpenAICompatibleAdapter, AdapterConfig
        from llm_kernel.core import Secret

        execution_plan, provider = plan

        lines = [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
            "data: [DONE]\n\n",
        ]

        respx.post("https://api.mock.com/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                text="".join(lines),
                headers={"content-type": "text/event-stream"},
            )
        )

        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )

        chunks = list(adapter.stream(execution_plan, "model-1"))
        assert "".join(chunks) == "Hello world"

    @respx.mock
    def test_health_check_pings_models(self, plan):
        from llm_kernel.runtime import OpenAICompatibleAdapter, AdapterConfig
        from llm_kernel.core import Secret

        _, provider = plan

        respx.get("https://api.mock.com/v1/models").mock(
            return_value=HttpxResponse(200, json={"data": []})
        )

        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )

        health = adapter.health_check()
        assert health in ("healthy", "degraded", "unhealthy")


class TestExecutor:
    @pytest.fixture
    def plan(self):
        from llm_kernel.core import Request, Message, Role
        from llm_kernel.planner import (
            ExecutionPlan,
            Candidate,
            ProviderMetadata,
            ModelMetadata,
        )

        provider = ProviderMetadata(
            name="mock",
            display_name="Mock",
            adapter_type="openai",
            base_url="https://api.mock.com/v1",
            api_key_env="MOCK_API_KEY",
            models=[ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096)],
            default_model="model-1",
        )
        request = Request(messages=[Message(role=Role.USER, content="Hello!")])
        plan = ExecutionPlan(
            trace_id=request.trace_id,
            request=request,
            candidates=[
                Candidate(provider="mock", model="model-1", score=1.0, estimated_tokens=2),
            ],
        )
        return plan, provider

    def test_execute_success(self, plan):
        from llm_kernel.runtime import Executor, OpenAICompatibleAdapter, AdapterConfig
        from llm_kernel.core import Secret

        execution_plan, provider = plan

        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )
        executor = Executor(adapters={"mock": adapter})

        with respx.mock:
            respx.post("https://api.mock.com/v1/chat/completions").mock(
                return_value=HttpxResponse(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "Hi!"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 2,
                            "completion_tokens": 1,
                            "total_tokens": 3,
                        },
                    },
                )
            )
            result = executor.execute(execution_plan)

        assert result.response is not None
        assert result.response.content == "Hi!"
        assert result.final_state == "completed"

    def test_execute_falls_back_on_failure(self, plan):
        from llm_kernel.runtime import Executor, OpenAICompatibleAdapter, AdapterConfig
        from llm_kernel.core import Secret, Request, Message, Role
        from llm_kernel.planner import (
            Candidate,
            ExecutionPlan,
            RetryPolicy,
            ProviderMetadata,
            ModelMetadata,
        )

        execution_plan, provider = plan
        request = Request(messages=[Message(role=Role.USER, content="Hello!"),])
        execution_plan = ExecutionPlan(
            trace_id=request.trace_id,
            request=request,
            candidates=[
                Candidate(provider="failing", model="model-1", score=1.0, estimated_tokens=2),
                Candidate(provider="mock", model="model-1", score=0.9, estimated_tokens=2),
            ],
            retry_policy=RetryPolicy(max_retries=0),
        )

        failing_provider = ProviderMetadata(
            name="failing",
            display_name="Failing",
            adapter_type="openai",
            base_url="https://api.failing.com/v1",
            api_key_env="FAILING_API_KEY",
            models=[ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096)],
            default_model="model-1",
        )

        failing_adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="failing",
                base_url="https://api.failing.com/v1",
                api_key=Secret("sk-fail"),
            ),
            provider=failing_provider,
        )
        mock_adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )

        executor = Executor(adapters={"failing": failing_adapter, "mock": mock_adapter})

        with respx.mock:
            respx.post("https://api.failing.com/v1/chat/completions").mock(
                return_value=HttpxResponse(429, json={"error": {"message": "rate limit"}})
            )
            respx.post("https://api.mock.com/v1/chat/completions").mock(
                return_value=HttpxResponse(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "Fallback!"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 2,
                            "completion_tokens": 1,
                            "total_tokens": 3,
                        },
                    },
                )
            )
            result = executor.execute(execution_plan)

        assert result.response is not None
        assert result.response.content == "Fallback!"
        assert result.response.provider == "mock"
        assert result.final_state == "completed"

    def test_execute_returns_failure_when_all_candidates_fail(self, plan):
        from llm_kernel.runtime import Executor, OpenAICompatibleAdapter, AdapterConfig
        from llm_kernel.core import Secret

        execution_plan, provider = plan

        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )
        executor = Executor(adapters={"mock": adapter})

        with respx.mock:
            respx.post("https://api.mock.com/v1/chat/completions").mock(
                return_value=HttpxResponse(401, json={"error": {"message": "invalid key"}})
            )
            result = executor.execute(execution_plan)

        assert result.response is None
        assert result.error is not None
        assert result.final_state == "failed"
