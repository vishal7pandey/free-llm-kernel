"""Tests for retry behavior and error classification.

Covers DVM:
- R-08: Retry on transient 502/503 with exponential backoff
- R-09: Do not retry 401/403 errors
- R-12: content == None handled with finish_reason
"""

import pytest
import respx
from httpx import Response as HttpxResponse

from llm_kernel.core import (
    FinishReason,
    Message,
    Request,
    Role,
    Secret,
)
from llm_kernel.planner import (
    Candidate,
    ExecutionPlan,
    ModelMetadata,
    ProviderMetadata,
    RetryPolicy,
)
from llm_kernel.runtime import (
    AdapterConfig,
    Executor,
    OpenAICompatibleAdapter,
    RetryEngine,
)


@pytest.fixture
def provider():
    return ProviderMetadata(
        name="mock",
        display_name="Mock",
        adapter_type="openai",
        base_url="https://api.mock.com/v1",
        api_key_env="MOCK_API_KEY",
        models=[ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096)],
        default_model="model-1",
    )


@pytest.fixture
def plan():
    request = Request(messages=[Message(role=Role.USER, content="Hello!")])
    return ExecutionPlan(
        trace_id=request.trace_id,
        request=request,
        candidates=[Candidate(provider="mock", model="model-1", score=1.0)],
        retry_policy=RetryPolicy(max_retries=3, backoff_base_ms=1, backoff_max_ms=10),
    )


class TestRetryEngine:
    def test_backoff_increases(self):
        engine = RetryEngine(base_ms=100, max_ms=10_000, jitter=False)
        d0 = engine.backoff_delay(0)
        d1 = engine.backoff_delay(1)
        d2 = engine.backoff_delay(2)
        assert d0 == 100
        assert d1 == 200
        assert d2 == 400

    def test_backoff_capped(self):
        engine = RetryEngine(base_ms=100, max_ms=500, jitter=False)
        assert engine.backoff_delay(10) == 500

    def test_is_retryable_rate_limit(self):
        engine = RetryEngine()
        assert engine.is_retryable("rate_limit") is True

    def test_is_retryable_auth(self):
        engine = RetryEngine()
        assert engine.is_retryable("auth") is False

    def test_is_retryable_server(self):
        engine = RetryEngine()
        assert engine.is_retryable("server") is True


class TestRetryOnTransient:
    @respx.mock
    def test_retries_on_503_then_succeeds(self, provider, plan):
        adapter = OpenAICompatibleAdapter(
            config=AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("test-key"),
            ),
            provider=provider,
        )
        executor = Executor(
            adapters={"mock": adapter},
            sleep_fn=lambda _: None,
        )

        url = "https://api.mock.com/v1/chat/completions"
        respx.post(url).mock(
            side_effect=[
                HttpxResponse(503, json={"error": {"message": "Service unavailable"}}),
                HttpxResponse(503, json={"error": {"message": "Service unavailable"}}),
                HttpxResponse(
                    200,
                    json={
                        "choices": [{"message": {"content": "Hi!"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                    },
                ),
            ]
        )

        result = executor.execute(plan)
        assert result.response is not None
        assert result.response.content == "Hi!"
        assert result.final_state == "completed"
        assert len(result.attempts) == 3

    @respx.mock
    def test_retries_on_502_then_succeeds(self, provider, plan):
        adapter = OpenAICompatibleAdapter(
            config=AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("test-key"),
            ),
            provider=provider,
        )
        executor = Executor(
            adapters={"mock": adapter},
            sleep_fn=lambda _: None,
        )

        url = "https://api.mock.com/v1/chat/completions"
        respx.post(url).mock(
            side_effect=[
                HttpxResponse(502, json={"error": {"message": "Bad gateway"}}),
                HttpxResponse(
                    200,
                    json={
                        "choices": [{"message": {"content": "Hi!"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                    },
                ),
            ]
        )

        result = executor.execute(plan)
        assert result.response is not None
        assert result.final_state == "completed"


class TestNoRetryOnAuth:
    @respx.mock
    def test_no_retry_on_401(self, provider, plan):
        adapter = OpenAICompatibleAdapter(
            config=AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("test-key"),
            ),
            provider=provider,
        )
        executor = Executor(
            adapters={"mock": adapter},
            sleep_fn=lambda _: None,
        )

        url = "https://api.mock.com/v1/chat/completions"
        respx.post(url).mock(
            return_value=HttpxResponse(401, json={"error": {"message": "Invalid key"}})
        )

        result = executor.execute(plan)
        assert result.error is not None
        assert result.final_state == "failed"
        # Only 1 attempt — no retries
        assert len(result.attempts) == 1

    @respx.mock
    def test_no_retry_on_403(self, provider, plan):
        adapter = OpenAICompatibleAdapter(
            config=AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("test-key"),
            ),
            provider=provider,
        )
        executor = Executor(
            adapters={"mock": adapter},
            sleep_fn=lambda _: None,
        )

        url = "https://api.mock.com/v1/chat/completions"
        respx.post(url).mock(
            return_value=HttpxResponse(403, json={"error": {"message": "Forbidden"}})
        )

        result = executor.execute(plan)
        assert result.error is not None
        assert len(result.attempts) == 1


class TestContentNoneHandling:
    @respx.mock
    def test_content_none_with_content_filter(self, provider, plan):
        adapter = OpenAICompatibleAdapter(
            config=AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("test-key"),
            ),
            provider=provider,
        )

        url = "https://api.mock.com/v1/chat/completions"
        respx.post(url).mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": None},
                            "finish_reason": "content_filter",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 0},
                },
            )
        )

        response = adapter.execute(plan, "model-1")
        assert response.content == ""
        assert response.finish_reason == FinishReason.CONTENT_FILTER
