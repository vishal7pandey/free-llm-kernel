"""Tests for the model catalogue API on LLMClient.

Run: uv run pytest tests/unit/test_catalogue.py -v
"""

import pytest

from llm_kernel import LLMClient
from llm_kernel.config import default_providers, build_world_state, build_adapters
from llm_kernel.core import Capability


@pytest.fixture
def client():
    providers = [p for p in default_providers() if p.name in ("groq", "google")]
    ws = build_world_state(providers)
    env = {p.api_key_env: "sk-test" for p in providers}
    adapters = build_adapters(providers, env)
    return LLMClient(providers=providers, world_state=ws, adapters=adapters)


class TestModelCatalogue:
    def test_list_models_returns_all(self, client):
        models = client.models()
        # groq has 2, google has 2
        assert len(models) == 4

    def test_list_models_has_provider_info(self, client):
        models = client.models()
        for m in models:
            assert m.provider is not None
            assert m.model_id is not None
            assert m.display_name is not None
            assert m.max_context_tokens > 0

    def test_filter_by_capability(self, client):
        vision_models = client.models(capability=Capability.VISION)
        # Only google has vision
        assert len(vision_models) == 2
        assert all(m.provider == "google" for m in vision_models)

    def test_filter_by_provider(self, client):
        groq_models = client.models(provider="groq")
        assert len(groq_models) == 2
        assert all(m.provider == "groq" for m in groq_models)

    def test_get_model_details(self, client):
        details = client.get_model("groq", "llama-3.3-70b-versatile")
        assert details is not None
        assert details.provider == "groq"
        assert details.model_id == "llama-3.3-70b-versatile"
        assert details.max_context_tokens == 131_072

    def test_get_model_returns_none_for_unknown(self, client):
        assert client.get_model("groq", "nonexistent") is None
        assert client.get_model("unknown", "anything") is None

    def test_list_providers(self, client):
        providers = client.list_providers()
        assert len(providers) == 2
        names = {p.name for p in providers}
        assert names == {"groq", "google"}

    def test_provider_has_models(self, client):
        providers = client.list_providers()
        for p in providers:
            assert len(p.models) > 0
            assert p.default_model in {m.id for m in p.models}

    def test_models_supports_streaming_filter(self, client):
        streaming = client.models(capability=Capability.STREAMING)
        # Both groq and google support streaming
        assert len(streaming) == 4

    def test_models_supports_tools_filter(self, client):
        tools = client.models(capability=Capability.TOOLS)
        # groq 70b + groq 8b + google gemini-2.0-flash have tools
        assert len(tools) == 3

    def test_cheapest_model(self, client):
        cheapest = client.cheapest_model()
        assert cheapest is not None
        # All free-tier models have cost 0.0
        assert cheapest.cost_per_1k_input == 0.0

    def test_fastest_model(self, client):
        fastest = client.fastest_model()
        assert fastest is not None
        # groq 8b has highest latency_score
        assert fastest.model_id == "llama-3.1-8b-instant"

    def test_best_quality_model(self, client):
        best = client.best_model()
        assert best is not None
        # groq 70b has quality_score 0.8
        assert best.quality_score == 0.8

    def test_add_custom_provider(self, client):
        from llm_kernel.planner import ProviderMetadata, ModelMetadata
        from llm_kernel.core import Secret
        from llm_kernel.runtime import AdapterConfig, OpenAICompatibleAdapter

        custom = ProviderMetadata(
            name="custom",
            display_name="Custom Provider",
            adapter_type="openai",
            base_url="https://api.custom.com/v1",
            api_key_env="CUSTOM_API_KEY",
            models=[
                ModelMetadata(
                    id="custom-model",
                    display_name="Custom Model",
                    max_context_tokens=8192,
                )
            ],
            default_model="custom-model",
        )

        client.add_provider(
            provider=custom,
            api_key=Secret("sk-custom"),
        )

        assert client.get_model("custom", "custom-model") is not None
        models = client.models(provider="custom")
        assert len(models) == 1
