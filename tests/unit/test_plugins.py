"""Tests for the plugin system: ProviderPlugin, PolicyPlugin, PluginRegistry."""

from llm_kernel.core import Capability, Secret
from llm_kernel.planner import (
    DefaultRoutingPolicy,
    ModelMetadata,
    ProviderMetadata,
    RoutingPolicy,
)
from llm_kernel.plugins import (
    PluginRegistry,
    get_registry,
    load_plugins,
    register_policy_plugin,
    register_provider_plugin,
)
from llm_kernel.runtime import OpenAICompatibleAdapter

# ---------------------------------------------------------------------------
# Test Plugin Implementations
# ---------------------------------------------------------------------------


class FakeProviderPlugin:
    """A test provider plugin that adds a fake provider."""

    @property
    def name(self) -> str:
        return "fake_provider"

    def create_provider(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="fake",
            display_name="Fake Provider",
            adapter_type="openai",
            base_url="https://api.fake.com/v1",
            api_key_env="FAKE_API_KEY",
            models=[
                ModelMetadata(
                    id="fake-model",
                    display_name="Fake Model",
                    max_context_tokens=4096,
                    capabilities=frozenset({Capability.STREAMING}),
                ),
            ],
            default_model="fake-model",
            daily_request_limit=500,
        )

    def create_adapter(
        self, provider: ProviderMetadata, api_key: Secret,
    ) -> OpenAICompatibleAdapter:
        from llm_kernel.runtime import AdapterConfig

        return OpenAICompatibleAdapter(
            config=AdapterConfig(
                provider_name=provider.name,
                base_url=provider.base_url,
                api_key=api_key,
            ),
            provider=provider,
        )


class FakePolicyPlugin:
    """A test policy plugin that adds a custom routing policy."""

    @property
    def name(self) -> str:
        return "fake_policy"

    def create_policy(self) -> RoutingPolicy:
        return DefaultRoutingPolicy()


# ---------------------------------------------------------------------------
# PluginRegistry Tests
# ---------------------------------------------------------------------------


class TestPluginRegistry:
    def test_register_and_get_provider(self):
        registry = PluginRegistry()
        plugin = FakeProviderPlugin()
        registry.register_provider(plugin)

        assert "fake_provider" in registry.provider_names
        assert registry.get_provider("fake_provider") is plugin

    def test_register_and_get_policy(self):
        registry = PluginRegistry()
        plugin = FakePolicyPlugin()
        registry.register_policy(plugin)

        assert "fake_policy" in registry.policy_names
        assert registry.get_policy("fake_policy") is plugin

    def test_unregister_provider(self):
        registry = PluginRegistry()
        plugin = FakeProviderPlugin()
        registry.register_provider(plugin)
        registry.unregister_provider("fake_provider")

        assert "fake_provider" not in registry.provider_names
        assert registry.get_provider("fake_provider") is None

    def test_unregister_policy(self):
        registry = PluginRegistry()
        plugin = FakePolicyPlugin()
        registry.register_policy(plugin)
        registry.unregister_policy("fake_policy")

        assert "fake_policy" not in registry.policy_names
        assert registry.get_policy("fake_policy") is None

    def test_all_providers(self):
        registry = PluginRegistry()
        plugin = FakeProviderPlugin()
        registry.register_provider(plugin)

        all_p = registry.all_providers()
        assert len(all_p) == 1
        assert all_p[0] is plugin

    def test_all_policies(self):
        registry = PluginRegistry()
        plugin = FakePolicyPlugin()
        registry.register_policy(plugin)

        all_p = registry.all_policies()
        assert len(all_p) == 1
        assert all_p[0] is plugin

    def test_get_nonexistent_provider(self):
        registry = PluginRegistry()
        assert registry.get_provider("nonexistent") is None

    def test_get_nonexistent_policy(self):
        registry = PluginRegistry()
        assert registry.get_policy("nonexistent") is None

    def test_empty_registry(self):
        registry = PluginRegistry()
        assert registry.provider_names == []
        assert registry.policy_names == []


# ---------------------------------------------------------------------------
# Global Registry Tests
# ---------------------------------------------------------------------------


class TestGlobalRegistry:
    def test_get_registry_returns_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_register_provider_plugin_global(self):
        plugin = FakeProviderPlugin()
        register_provider_plugin(plugin)
        registry = get_registry()
        assert "fake_provider" in registry.provider_names

        # Cleanup
        registry.unregister_provider("fake_provider")

    def test_register_policy_plugin_global(self):
        plugin = FakePolicyPlugin()
        register_policy_plugin(plugin)
        registry = get_registry()
        assert "fake_policy" in registry.policy_names

        # Cleanup
        registry.unregister_policy("fake_policy")

    def test_load_plugins_returns_registry(self):
        registry = load_plugins()
        assert isinstance(registry, PluginRegistry)


# ---------------------------------------------------------------------------
# LLMClient Integration Tests
# ---------------------------------------------------------------------------


class TestClientPluginIntegration:
    def test_register_policy_on_client(self):
        from llm_kernel.client import LLMClient
        from llm_kernel.planner import WorldState

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
        ws = WorldState(providers=[provider])
        client = LLMClient(
            providers=[provider],
            world_state=ws,
            adapters={},
        )

        # Register a custom policy
        client.register_policy("my_custom", DefaultRoutingPolicy)
        assert "my_custom" in client.available_policies()

        # Cleanup
        from llm_kernel.planner import POLICY_REGISTRY
        POLICY_REGISTRY.pop("my_custom", None)

    def test_available_policies_includes_builtins(self):
        from llm_kernel.client import LLMClient
        from llm_kernel.planner import WorldState

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
        ws = WorldState(providers=[provider])
        client = LLMClient(
            providers=[provider],
            world_state=ws,
            adapters={},
        )

        policies = client.available_policies()
        assert "default" in policies
        assert "best_free" in policies
        assert "fastest" in policies
        assert "cheapest" in policies
        assert "quality" in policies

    def test_provider_plugin_creates_provider(self):
        plugin = FakeProviderPlugin()
        provider = plugin.create_provider()

        assert provider.name == "fake"
        assert len(provider.models) == 1
        assert provider.models[0].id == "fake-model"
        assert Capability.STREAMING in provider.models[0].capabilities

    def test_provider_plugin_creates_adapter(self):
        plugin = FakeProviderPlugin()
        provider = plugin.create_provider()
        adapter = plugin.create_adapter(provider, Secret("sk-test"))

        assert adapter.provider_name == "fake"
        assert isinstance(adapter, OpenAICompatibleAdapter)
