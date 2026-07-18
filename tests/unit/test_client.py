"""Tests for llm_kernel.LLMClient — the public facade.

Run: uv run pytest tests/unit/test_client -v
"""

import pytest
import respx
from httpx import Response as HttpxResponse


class TestLLMClient:
    @pytest.fixture
    def client(self):
        from llm_kernel import LLMClient
        from llm_kernel.config import default_providers, build_world_state, build_adapters
        from llm_kernel.core import Secret

        all_providers = default_providers()
        # Only use groq and google for tests
        providers = [p for p in all_providers if p.name in ("groq", "google")]
        ws = build_world_state(providers)
        env = {p.api_key_env: "sk-test" for p in providers}
        adapters = build_adapters(providers, env)

        return LLMClient(
            providers=providers,
            world_state=ws,
            adapters=adapters,
        )

    @respx.mock
    def test_chat_returns_response(self, client):
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Hello!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                },
            )
        )

        response = client.chat("Hello!")
        assert response.content == "Hello!"
        assert response.provider == "groq"
        assert response.usage.total_tokens == 3

    @respx.mock
    def test_chat_falls_back(self, client):
        # Make Groq fail, Google succeed
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(429, json={"error": {"message": "rate limit"}})
        )
        respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Fallback!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                },
            )
        )

        response = client.chat("Hello!")
        assert response.content == "Fallback!"
        assert response.provider == "google"

    @respx.mock
    def test_chat_with_system_prompt(self, client):
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "System ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
                },
            )
        )

        response = client.chat("Hello!", system="You are a helpful assistant.")
        assert response.content == "System ok"

    @respx.mock
    def test_chat_with_model_override(self, client):
        respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Gemini!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                },
            )
        )

        response = client.chat("Hello!", model="gemini-2.0-flash")
        assert response.content == "Gemini!"
        assert response.provider == "google"

    @respx.mock
    def test_chat_all_providers_fail_raises(self, client):
        from llm_kernel.core import KernelError

        # Mock both provider URLs to fail
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(401, json={"error": {"message": "bad key"}})
        )
        respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
            return_value=HttpxResponse(401, json={"error": {"message": "bad key"}})
        )

        with pytest.raises(KernelError):
            client.chat("Hello!")

    @respx.mock
    def test_stream_returns_chunks(self, client):
        lines = [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
            "data: [DONE]\n\n",
        ]

        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                text="".join(lines),
                headers={"content-type": "text/event-stream"},
            )
        )

        chunks = list(client.stream("Hello!"))
        assert "".join(chunks) == "Hello world"
