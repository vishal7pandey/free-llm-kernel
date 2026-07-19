"""Tests for automatic model discovery and capability inference."""


import httpx
import respx
from httpx import Response as HttpxResponse

from llm_kernel.core import Capability, Secret
from llm_kernel.planner import (
    ModelMetadata,
    ProviderMetadata,
    WorldState,
    infer_capabilities,
    infer_context_tokens,
    infer_model_metadata,
    infer_quality_score,
)
from llm_kernel.runtime import AdapterConfig, OpenAICompatibleAdapter

# ---------------------------------------------------------------------------
# Capability Inference Tests
# ---------------------------------------------------------------------------


class TestInferCapabilities:
    def test_llama_3_gets_tools_and_function_calling(self):
        caps = infer_capabilities("llama-3.3-70b-versatile")
        assert Capability.TOOLS in caps
        assert Capability.FUNCTION_CALLING in caps
        assert Capability.STREAMING in caps

    def test_llama3_no_dash_also_matched(self):
        caps = infer_capabilities("llama3.2")
        assert Capability.TOOLS in caps
        assert Capability.STREAMING in caps

    def test_gemini_gets_vision_and_json(self):
        caps = infer_capabilities("gemini-2.0-flash")
        assert Capability.VISION in caps
        assert Capability.JSON_MODE in caps
        assert Capability.STREAMING in caps

    def test_vision_in_name_implies_vision(self):
        caps = infer_capabilities("some-model-vision-pro")
        assert Capability.VISION in caps

    def test_vl_suffix_implies_vision(self):
        caps = infer_capabilities("qwen-vl-72b")
        assert Capability.VISION in caps

    def test_mixtral_gets_tools(self):
        caps = infer_capabilities("mixtral-8x7b-instruct")
        assert Capability.TOOLS in caps
        assert Capability.FUNCTION_CALLING in caps

    def test_qwen_gets_tools_and_json(self):
        caps = infer_capabilities("qwen-2.5-72b")
        assert Capability.TOOLS in caps
        assert Capability.JSON_MODE in caps

    def test_unknown_model_still_gets_streaming(self):
        caps = infer_capabilities("unknown-model-xyz")
        assert Capability.STREAMING in caps

    def test_gpt4_gets_vision_tools_json(self):
        caps = infer_capabilities("gpt-4o")
        assert Capability.VISION in caps
        assert Capability.TOOLS in caps
        assert Capability.JSON_MODE in caps


class TestInferContextTokens:
    def test_gemini_gets_1m(self):
        assert infer_context_tokens("gemini-2.0-flash") == 1_048_576

    def test_llama_33_gets_128k(self):
        assert infer_context_tokens("llama-3.3-70b") == 131_072

    def test_llama_31_gets_128k(self):
        assert infer_context_tokens("llama-3.1-8b") == 131_072

    def test_mixtral_gets_32k(self):
        assert infer_context_tokens("mixtral-8x7b") == 32_768

    def test_8b_gets_8k(self):
        assert infer_context_tokens("some-8b-model") == 8_192

    def test_unknown_defaults_to_8k(self):
        assert infer_context_tokens("unknown-model") == 8_192


class TestInferQualityScore:
    def test_70b_gets_0_8(self):
        assert infer_quality_score("llama-3.3-70b") == 0.8

    def test_8b_gets_0_6(self):
        assert infer_quality_score("llama-3.1-8b") == 0.6

    def test_3b_gets_0_4(self):
        assert infer_quality_score("tiny-3b") == 0.4

    def test_gemini_gets_0_75(self):
        assert infer_quality_score("gemini-2.0-flash") == 0.75

    def test_unknown_gets_0_5(self):
        assert infer_quality_score("unknown-model") == 0.5


class TestInferModelMetadata:
    def test_returns_valid_metadata(self):
        meta = infer_model_metadata("llama-3.3-70b")
        assert isinstance(meta, ModelMetadata)
        assert meta.id == "llama-3.3-70b"
        assert meta.max_context_tokens == 131_072
        assert Capability.TOOLS in meta.capabilities
        assert meta.quality_score == 0.8

    def test_gemini_metadata(self):
        meta = infer_model_metadata("gemini-2.0-flash")
        assert Capability.VISION in meta.capabilities
        assert Capability.JSON_MODE in meta.capabilities
        assert meta.max_context_tokens == 1_048_576
        assert meta.quality_score == 0.75


# ---------------------------------------------------------------------------
# Adapter discover_models() Tests
# ---------------------------------------------------------------------------


def _make_provider(name: str = "mock") -> ProviderMetadata:
    return ProviderMetadata(
        name=name,
        display_name=name.title(),
        adapter_type="openai",
        base_url=f"https://api.{name}.com/v1",
        api_key_env=f"{name.upper()}_API_KEY",
        models=[
            ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096),
        ],
        default_model="model-1",
    )


class TestDiscoverModels:
    @respx.mock
    def test_returns_model_ids(self):
        provider = _make_provider()
        respx.get("https://api.mock.com/v1/models").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "data": [
                        {"id": "model-1"},
                        {"id": "model-2"},
                        {"id": "llama-3.3-70b"},
                    ]
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
        models = adapter.discover_models()
        assert models == ["model-1", "model-2", "llama-3.3-70b"]

    @respx.mock
    def test_returns_empty_on_404(self):
        provider = _make_provider()
        respx.get("https://api.mock.com/v1/models").mock(
            return_value=HttpxResponse(404)
        )
        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )
        assert adapter.discover_models() == []

    @respx.mock
    def test_returns_empty_on_network_error(self):
        provider = _make_provider()
        respx.get("https://api.mock.com/v1/models").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )
        assert adapter.discover_models() == []

    @respx.mock
    def test_returns_empty_on_invalid_json(self):
        provider = _make_provider()
        respx.get("https://api.mock.com/v1/models").mock(
            return_value=HttpxResponse(200, text="not json")
        )
        adapter = OpenAICompatibleAdapter(
            AdapterConfig(
                provider_name="mock",
                base_url="https://api.mock.com/v1",
                api_key=Secret("sk-test"),
            ),
            provider=provider,
        )
        assert adapter.discover_models() == []

    @respx.mock
    def test_handles_empty_data_list(self):
        provider = _make_provider()
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
        assert adapter.discover_models() == []


# ---------------------------------------------------------------------------
# LLMClient.refresh_models() Tests
# ---------------------------------------------------------------------------


class TestRefreshModels:
    @respx.mock
    def test_discovers_new_models_and_updates_catalogue(self):
        from llm_kernel.client import LLMClient

        provider = ProviderMetadata(
            name="mock",
            display_name="Mock",
            adapter_type="openai",
            base_url="https://api.mock.com/v1",
            api_key_env="MOCK_API_KEY",
            models=[
                ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096),
            ],
            default_model="model-1",
            daily_request_limit=1000,
        )

        respx.get("https://api.mock.com/v1/models").mock(
            return_value=HttpxResponse(
                200,
                json={
                    "data": [
                        {"id": "model-1"},
                        {"id": "llama-3.3-70b"},
                    ]
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

        ws = WorldState(providers=[provider])
        client = LLMClient(
            providers=[provider],
            world_state=ws,
            adapters={"mock": adapter},
        )

        # Before refresh: only 1 model
        assert len(client.models()) == 1

        discovered = client.refresh_models()
        assert "mock" in discovered
        assert "llama-3.3-70b" in discovered["mock"]

        # After refresh: 2 models, new one has inferred capabilities
        all_models = client.models()
        assert len(all_models) == 2
        new_model = [m for m in all_models if m.model_id == "llama-3.3-70b"][0]
        assert Capability.TOOLS in new_model.capabilities

    @respx.mock
    def test_no_change_when_no_new_models(self):
        from llm_kernel.client import LLMClient

        provider = ProviderMetadata(
            name="mock",
            display_name="Mock",
            adapter_type="openai",
            base_url="https://api.mock.com/v1",
            api_key_env="MOCK_API_KEY",
            models=[
                ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096),
            ],
            default_model="model-1",
            daily_request_limit=1000,
        )

        respx.get("https://api.mock.com/v1/models").mock(
            return_value=HttpxResponse(
                200,
                json={"data": [{"id": "model-1"}]},
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

        ws = WorldState(providers=[provider])
        client = LLMClient(
            providers=[provider],
            world_state=ws,
            adapters={"mock": adapter},
        )

        discovered = client.refresh_models()
        assert discovered == {"mock": ["model-1"]}
        assert len(client.models()) == 1

    def test_handles_provider_without_adapter(self):
        from llm_kernel.client import LLMClient

        provider = ProviderMetadata(
            name="nokey",
            display_name="No Key",
            adapter_type="openai",
            base_url="https://api.nokey.com/v1",
            api_key_env="NOKEY_API_KEY",
            models=[
                ModelMetadata(id="model-1", display_name="Model 1", max_context_tokens=4096),
            ],
            default_model="model-1",
            daily_request_limit=1000,
        )

        ws = WorldState(providers=[provider])
        client = LLMClient(
            providers=[provider],
            world_state=ws,
            adapters={},
        )

        discovered = client.refresh_models()
        assert "nokey" not in discovered
