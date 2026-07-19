"""Tests for tool call parsing in the OpenAI-compatible adapter.

Covers DVM R-11: non-OpenAI-compatible response normalized to Response.
"""

import json

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
from llm_kernel.planner import Candidate, ExecutionPlan, ModelMetadata, ProviderMetadata
from llm_kernel.runtime import AdapterConfig, OpenAICompatibleAdapter


@pytest.fixture
def adapter():
    config = AdapterConfig(
        provider_name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key=Secret("gsk_test_key_abcdef123456789"),
    )
    return OpenAICompatibleAdapter(config=config)


@pytest.fixture
def plan():
    provider = ProviderMetadata(
        name="groq",
        display_name="Groq",
        adapter_type="openai",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        models=[
            ModelMetadata(id="llama-3.3-70b", display_name="Llama 3.3 70B", max_context_tokens=4096)
        ],
        default_model="llama-3.3-70b",
    )
    request = Request(messages=[Message(role=Role.USER, content="What's the weather?")])
    return ExecutionPlan(
        trace_id=request.trace_id,
        request=request,
        candidates=[Candidate(provider="groq", model="llama-3.3-70b", score=1.0)],
    ), provider


class TestToolCallParsing:
    @respx.mock
    def test_parses_single_tool_call(self, adapter, plan):
        execution_plan, _ = plan
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_abc123",
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": json.dumps({"city": "San Francisco"}),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )
        )

        response = adapter.execute(execution_plan, "llama-3.3-70b")
        assert len(response.tool_calls) == 1
        tc = response.tool_calls[0]
        assert tc.id == "call_abc123"
        assert tc.function.name == "get_weather"
        assert json.loads(tc.function.arguments) == {"city": "San Francisco"}
        assert response.finish_reason == FinishReason.TOOL_CALLS

    @respx.mock
    def test_parses_multiple_tool_calls(self, adapter, plan):
        execution_plan, _ = plan
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": '{"city": "SF"}',
                                        },
                                    },
                                    {
                                        "id": "call_2",
                                        "type": "function",
                                        "function": {
                                            "name": "get_time",
                                            "arguments": '{"timezone": "PST"}',
                                        },
                                    },
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        )

        response = adapter.execute(execution_plan, "llama-3.3-70b")
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0].function.name == "get_weather"
        assert response.tool_calls[1].function.name == "get_time"

    @respx.mock
    def test_no_tool_calls_when_absent(self, adapter, plan):
        execution_plan, _ = plan
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "Hello!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                },
            )
        )

        response = adapter.execute(execution_plan, "llama-3.3-70b")
        assert response.tool_calls == []
        assert response.finish_reason == FinishReason.COMPLETED

    @respx.mock
    def test_invalid_tool_call_arguments_skipped(self, adapter, plan):
        execution_plan, _ = plan
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "bad_call",
                                            "arguments": "not valid json {{{",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                },
            )
        )

        response = adapter.execute(execution_plan, "llama-3.3-70b")
        # Invalid arguments cause ValidationError, which is caught and skipped
        assert response.tool_calls == []

    @respx.mock
    def test_finish_reason_adjusted_to_tool_calls(self, adapter, plan):
        execution_plan, _ = plan
        # Some providers return "stop" even with tool_calls
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "search",
                                            "arguments": '{"q": "test"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                },
            )
        )

        response = adapter.execute(execution_plan, "llama-3.3-70b")
        assert response.finish_reason == FinishReason.TOOL_CALLS
