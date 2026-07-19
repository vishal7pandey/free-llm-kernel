"""Integration test: end-to-end Request → Planner → Executor → Response.

Uses respx to mock all HTTP endpoints. Verifies the full pipeline works.
"""

import respx
from httpx import Response as HttpxResponse


class TestEndToEnd:
    @respx.mock
    def test_full_pipeline_chat(self):
        from llm_kernel import LLMClient
        from llm_kernel.config import build_adapters, build_world_state, default_providers

        all_providers = default_providers()
        providers = [p for p in all_providers if p.name in ("groq", "google")]
        ws = build_world_state(providers)
        env = {p.api_key_env: "sk-test" for p in providers}
        adapters = build_adapters(providers, env)

        client = LLMClient(
            providers=providers,
            world_state=ws,
            adapters=adapters,
        )

        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Integration test!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
                },
            )
        )

        response = client.chat("Say hello")
        assert response.content == "Integration test!"
        assert response.usage.total_tokens == 4

    @respx.mock
    def test_full_pipeline_fallback(self):
        from llm_kernel import LLMClient
        from llm_kernel.config import build_adapters, build_world_state, default_providers

        all_providers = default_providers()
        providers = [p for p in all_providers if p.name in ("groq", "google")]
        ws = build_world_state(providers)
        env = {p.api_key_env: "sk-test" for p in providers}
        adapters = build_adapters(providers, env)

        client = LLMClient(
            providers=providers,
            world_state=ws,
            adapters=adapters,
        )

        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(500, json={"error": {"message": "server error"}})
        )
        respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Fallback works!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
                },
            )
        )

        response = client.chat("Say hello")
        assert response.content == "Fallback works!"
        assert response.provider == "google"

    @respx.mock
    def test_full_pipeline_stream(self):
        from llm_kernel import LLMClient
        from llm_kernel.config import build_adapters, build_world_state, default_providers

        all_providers = default_providers()
        providers = [p for p in all_providers if p.name in ("groq", "google")]
        ws = build_world_state(providers)
        env = {p.api_key_env: "sk-test" for p in providers}
        adapters = build_adapters(providers, env)

        client = LLMClient(
            providers=providers,
            world_state=ws,
            adapters=adapters,
        )

        lines = [
            'data: {"choices":[{"delta":{"content":"Chunk1"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"Chunk2"}}]}\n\n',
            "data: [DONE]\n\n",
        ]

        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(
                200,
                text="".join(lines),
                headers={"content-type": "text/event-stream"},
            )
        )

        chunks = list(client.stream("Say hello"))
        assert "".join(chunks) == "Chunk1Chunk2"
