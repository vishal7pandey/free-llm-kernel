"""Plugin system for community providers and routing policies.

Community packages can register providers and policies via:
1. Python entry points (auto-discovered on install)
2. Direct registration at runtime

Entry point groups:
- ``llm_kernel.providers`` — ProviderPlugin instances
- ``llm_kernel.policies`` — PolicyPlugin instances

Example ``pyproject.toml`` for a community package::

    [project.entry-points."llm_kernel.providers"]
    together = "llm_kernel_together:TogetherProviderPlugin"

    [project.entry-points."llm_kernel.policies"]
    privacy = "llm_kernel_privacy:PrivacyPolicyPlugin"
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from llm_kernel.core import Secret
from llm_kernel.planner import (
    ProviderMetadata,
    RoutingPolicy,
)
from llm_kernel.runtime import OpenAICompatibleAdapter

# ---------------------------------------------------------------------------
# Plugin Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ProviderPlugin(Protocol):
    """Plugin that contributes a provider to the kernel.

    A community package implements this to add support for a new
    free LLM provider. The plugin supplies the provider metadata
    and constructs the adapter.
    """

    @property
    def name(self) -> str: ...

    def create_provider(self) -> ProviderMetadata: ...

    def create_adapter(
        self, provider: ProviderMetadata, api_key: Secret,
    ) -> OpenAICompatibleAdapter: ...


@runtime_checkable
class PolicyPlugin(Protocol):
    """Plugin that contributes a routing policy.

    A community package implements this to add a custom routing
    strategy (e.g., privacy-first, carbon-aware, cost-optimized).
    """

    @property
    def name(self) -> str: ...

    def create_policy(self) -> RoutingPolicy: ...


# ---------------------------------------------------------------------------
# Plugin Registry
# ---------------------------------------------------------------------------


@dataclass
class PluginRegistry:
    """Registry for provider and policy plugins.

    Plugins can be registered manually or discovered via Python
    entry points. The registry is used by ``LLMClient.from_env()``
    when ``plugins=True``.
    """

    _providers: dict[str, ProviderPlugin] = field(default_factory=dict)
    _policies: dict[str, PolicyPlugin] = field(default_factory=dict)

    def register_provider(self, plugin: ProviderPlugin) -> None:
        """Register a provider plugin."""
        self._providers[plugin.name] = plugin

    def register_policy(self, plugin: PolicyPlugin) -> None:
        """Register a policy plugin."""
        self._policies[plugin.name] = plugin

    def unregister_provider(self, name: str) -> None:
        """Remove a provider plugin by name."""
        self._providers.pop(name, None)

    def unregister_policy(self, name: str) -> None:
        """Remove a policy plugin by name."""
        self._policies.pop(name, None)

    def get_provider(self, name: str) -> ProviderPlugin | None:
        return self._providers.get(name)

    def get_policy(self, name: str) -> PolicyPlugin | None:
        return self._policies.get(name)

    @property
    def provider_names(self) -> list[str]:
        return sorted(self._providers.keys())

    @property
    def policy_names(self) -> list[str]:
        return sorted(self._policies.keys())

    def all_providers(self) -> list[ProviderPlugin]:
        return list(self._providers.values())

    def all_policies(self) -> list[PolicyPlugin]:
        return list(self._policies.values())

    def load_entry_points(self) -> None:
        """Discover and load plugins from Python entry points.

        Scans for ``llm_kernel.providers`` and ``llm_kernel.policies``
        entry point groups. Each entry point should resolve to a
        ProviderPlugin or PolicyPlugin instance respectively.
        """
        try:
            from importlib.metadata import entry_points
        except ImportError:
            return

        try:
            eps = entry_points()
        except Exception:
            return

        # Provider plugins
        provider_eps: list[Any] = []
        try:
            provider_eps = list(eps.select(group="llm_kernel.providers"))
        except (TypeError, AttributeError):
            with contextlib.suppress(Exception):
                provider_eps = list(eps.get("llm_kernel.providers", []))

        for ep in provider_eps:
            try:
                plugin = ep.load()
                if isinstance(plugin, type):
                    plugin = plugin()
                if hasattr(plugin, "create_provider") and hasattr(plugin, "name"):
                    self.register_provider(plugin)
            except Exception:
                continue

        # Policy plugins
        policy_eps: list[Any] = []
        try:
            policy_eps = list(eps.select(group="llm_kernel.policies"))
        except (TypeError, AttributeError):
            with contextlib.suppress(Exception):
                policy_eps = list(eps.get("llm_kernel.policies", []))

        for ep in policy_eps:
            try:
                plugin = ep.load()
                if isinstance(plugin, type):
                    plugin = plugin()
                if hasattr(plugin, "create_policy") and hasattr(plugin, "name"):
                    self.register_policy(plugin)
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Default registry and convenience functions
# ---------------------------------------------------------------------------

_default_registry = PluginRegistry()


def get_registry() -> PluginRegistry:
    """Return the global default plugin registry."""
    return _default_registry


def register_provider_plugin(plugin: ProviderPlugin) -> None:
    """Register a provider plugin in the global registry."""
    _default_registry.register_provider(plugin)


def register_policy_plugin(plugin: PolicyPlugin) -> None:
    """Register a policy plugin in the global registry."""
    _default_registry.register_policy(plugin)


def load_plugins() -> PluginRegistry:
    """Load all plugins from entry points into the global registry.

    Returns the registry for convenience.
    """
    _default_registry.load_entry_points()
    return _default_registry


__all__ = [
    "ProviderPlugin",
    "PolicyPlugin",
    "PluginRegistry",
    "get_registry",
    "register_provider_plugin",
    "register_policy_plugin",
    "load_plugins",
]
