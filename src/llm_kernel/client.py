"""LLMClient — the public facade that wires Planner + Executor + UsageStore.

Usage:
    from llm_kernel import LLMClient
    client = LLMClient.from_env()
    response = client.chat("Hello!")
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from llm_kernel.core import (
    Capability,
    KernelError,
    Message,
    Request,
    Response,
    Role,
    Secret,
)
from llm_kernel.extensions import Extension, MiddlewareChain, UsageStore
from llm_kernel.planner import ModelMetadata, Planner, ProviderMetadata, RoutingPolicy, WorldState
from llm_kernel.runtime import (
    AdapterConfig,
    Executor,
    HealthTracker,
    OpenAICompatibleAdapter,
)


@dataclass(frozen=True)
class ModelInfo:
    """Catalogue entry for a single model."""

    provider: str
    model_id: str
    display_name: str
    max_context_tokens: int
    max_output_tokens: int | None
    capabilities: frozenset[Capability]
    cost_per_1k_input: float
    cost_per_1k_output: float
    quality_score: float
    latency_score: float

    @classmethod
    def from_metadata(cls, provider_name: str, m: ModelMetadata) -> ModelInfo:
        return cls(
            provider=provider_name,
            model_id=m.id,
            display_name=m.display_name,
            max_context_tokens=m.max_context_tokens,
            max_output_tokens=m.max_output_tokens,
            capabilities=m.capabilities,
            cost_per_1k_input=m.cost_per_1k_input,
            cost_per_1k_output=m.cost_per_1k_output,
            quality_score=m.quality_score,
            latency_score=m.latency_score,
        )


class LLMClient:
    """High-level facade: chat() and stream() with automatic fallback.

    Implements the public API surface from INTERFACE.md §8.1:
    - chat(prompt, **kwargs) → Response
    - stream(prompt, **kwargs) → Iterator[str]
    - execute(request) → Response  (advanced, full pipeline)
    - available_providers() → list[str]
    - usage() → dict[str, UsageRecord]
    - models(...) / get_model(...) / list_providers()
    """

    def __init__(
        self,
        providers: list[ProviderMetadata],
        world_state: WorldState,
        adapters: dict[str, OpenAICompatibleAdapter],
        usage_store: UsageStore | None = None,
        extensions: list[Extension] | None = None,
        health_tracker: HealthTracker | None = None,
    ):
        self._providers = providers
        self._world_state = world_state
        self._adapters = adapters
        self._usage_store = usage_store
        self._middleware = MiddlewareChain(extensions)
        self._health_tracker = health_tracker or HealthTracker(
            daily_limits={p.name: p.daily_request_limit for p in providers},
        )
        self._planner = Planner(world_state)
        self._executor = Executor(
            adapters=adapters,
            health_tracker=self._health_tracker,
        )

    @classmethod
    def from_env(
        cls,
        env_path: str | None = None,
        usage_path: str | None = None,
    ) -> LLMClient:
        """Build a client from .env file and default provider registry."""
        from llm_kernel.config import (
            build_adapters,
            build_world_state,
            default_providers,
            filter_available_providers,
            resolve_env,
        )

        env = resolve_env(env_path)
        all_providers = default_providers()
        available = filter_available_providers(all_providers, env)

        if not available:
            raise KernelError(
                "No providers configured. Set at least one API key in .env "
                "(e.g. GROQ_API_KEY=your-key)"
            )

        adapters = build_adapters(available, env)
        world_state = build_world_state(available)

        usage_store = UsageStore(usage_path) if usage_path else None

        return cls(
            providers=available,
            world_state=world_state,
            adapters=adapters,
            usage_store=usage_store,
        )

    # -----------------------------------------------------------------------
    # Extension management
    # -----------------------------------------------------------------------

    def add_extension(self, extension: Extension, *, fatal: bool = False) -> None:
        """Register a middleware extension."""
        self._middleware.add(extension, fatal=fatal)

    def remove_extension(self, extension: Extension) -> None:
        """Remove a registered extension."""
        self._middleware.remove(extension)

    @property
    def middleware(self) -> MiddlewareChain:
        return self._middleware

    def chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: str | RoutingPolicy | None = None,
    ) -> Response:
        """Send a chat request and return a Response.

        Automatically plans, executes with fallback, and records usage.

        Args:
            policy: Optional routing policy override for this request.
                Can be a string ("best_free", "fastest", "cheapest", "quality",
                "default") or a RoutingPolicy instance.
        """
        messages: list[Message] = []
        if system:
            messages.append(Message(role=Role.SYSTEM, content=system))
        messages.append(Message(role=Role.USER, content=prompt))

        request = Request(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return self.execute(request, policy=policy)

    def execute(
        self, request: Request, *, policy: str | RoutingPolicy | None = None,
    ) -> Response:
        """Execute a full Request through the pipeline: middleware → plan → execute → record.

        This is the advanced API (INTERFACE.md §8.1). Use chat() for simple cases.

        Args:
            policy: Optional routing policy override for this request.
                Can be a string ("best_free", "fastest", "cheapest", "quality",
                "default") or a RoutingPolicy instance.
        """
        self._refresh_world_state()
        request = self._middleware.on_request(request)

        plan = self._planner.plan(request, policy=policy)
        self._middleware.on_plan(plan)

        self._middleware.on_execution_start(plan)
        result = self._executor.execute(plan)
        self._middleware.on_execution_end(result)

        if result.response is not None:
            response = self._middleware.on_response(result.response)
            if self._usage_store is not None:
                self._usage_store.record(
                    provider=response.provider,
                    model=response.model,
                    usage=response.usage,
                )
            return response

        error_msg = str(result.error) if result.error else "All providers failed"
        raise KernelError(error_msg)

    def _refresh_world_state(self) -> None:
        """Rebuild WorldState with current health and quota from HealthTracker."""
        health = self._health_tracker.get_health()
        quota = self._health_tracker.get_quota()
        self._world_state = WorldState(
            providers=list(self._providers),
            usage=dict(quota.usage),
            latency=dict(quota.latency),
            health=dict(health.status),
        )
        self._planner = Planner(self._world_state)

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """Stream a chat request, yielding content chunks.

        Tries candidates in order. If a provider fails before yielding any
        chunks, falls back to the next candidate. Once chunks start flowing,
        the stream is committed to that provider.
        """
        messages: list[Message] = []
        if system:
            messages.append(Message(role=Role.SYSTEM, content=system))
        messages.append(Message(role=Role.USER, content=prompt))

        request = Request(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        plan = self._planner.plan(request)

        last_error: Exception | None = None
        for candidate in plan.candidates:
            adapter = self._adapters.get(candidate.provider)
            if adapter is None:
                continue
            try:
                yielded = False
                for chunk in adapter.stream(plan, candidate.model):
                    yielded = True
                    yield chunk
                return  # Stream completed successfully
            except Exception as exc:
                last_error = exc
                if yielded:
                    raise  # Already committed to this provider
                continue  # Try next candidate

        raise KernelError(str(last_error) if last_error else "No adapter available for streaming")

    @property
    def providers(self) -> list[ProviderMetadata]:
        """Return the list of configured providers."""
        return self._providers

    @property
    def usage_store(self) -> UsageStore | None:
        return self._usage_store

    def available_providers(self) -> list[str]:
        """Return names of providers with configured adapters."""
        return [p.name for p in self._providers if p.name in self._adapters]

    def usage(self) -> dict[str, Any]:
        """Return today's usage summary per provider.

        Returns a dict mapping provider name to aggregate UsageRecord.
        """
        if self._usage_store is None:
            return {}
        return {r.provider: r for r in self._usage_store.get_today()}

    def provider_health(self) -> dict[str, dict[str, Any]]:
        """Return live health and quota status per provider.

        This is the Provider Intelligence Engine surface — introspect what
        the kernel knows about each provider before sending a request.

        Example::

            {
                "groq": {
                    "status": "healthy",
                    "latency_ms": 150.0,
                    "requests_today": 42,
                    "quota_remaining": 0.958,
                    "daily_limit": 1000,
                },
                "google": {
                    "status": "degraded",
                    "latency_ms": 800.0,
                    "requests_today": 1200,
                    "quota_remaining": 0.2,
                    "daily_limit": 1500,
                },
            }
        """
        health = self._health_tracker.get_health()
        quota = self._health_tracker.get_quota()
        result: dict[str, dict[str, Any]] = {}
        for provider in self._providers:
            name = provider.name
            usage = quota.get_usage(name)
            result[name] = {
                "status": health.status.get(name, "healthy"),
                "latency_ms": quota.get_latency(name),
                "requests_today": usage.request_count if usage else 0,
                "quota_remaining": self._health_tracker.quota_remaining(name),
                "daily_limit": provider.daily_request_limit,
            }
        return result

    # -----------------------------------------------------------------------
    # Model Catalogue
    # -----------------------------------------------------------------------

    def models(
        self,
        *,
        provider: str | None = None,
        capability: Capability | None = None,
    ) -> list[ModelInfo]:
        """List available models, optionally filtered by provider or capability."""
        result: list[ModelInfo] = []
        for p in self._providers:
            if provider is not None and p.name != provider:
                continue
            for m in p.models:
                if capability is not None and capability not in m.capabilities:
                    continue
                result.append(ModelInfo.from_metadata(p.name, m))
        return result

    def get_model(self, provider: str, model_id: str) -> ModelInfo | None:
        """Get details for a specific model, or None if not found."""
        for p in self._providers:
            if p.name != provider:
                continue
            for m in p.models:
                if m.id == model_id:
                    return ModelInfo.from_metadata(p.name, m)
        return None

    def list_providers(self) -> list[ProviderMetadata]:
        """Return all configured providers with their model lists."""
        return list(self._providers)

    def cheapest_model(self) -> ModelInfo | None:
        """Return the model with the lowest input cost."""
        all_models = self.models()
        if not all_models:
            return None
        return min(all_models, key=lambda m: m.cost_per_1k_input)

    def fastest_model(self) -> ModelInfo | None:
        """Return the model with the highest latency score."""
        all_models = self.models()
        if not all_models:
            return None
        return max(all_models, key=lambda m: m.latency_score)

    def best_model(self) -> ModelInfo | None:
        """Return the model with the highest quality score."""
        all_models = self.models()
        if not all_models:
            return None
        return max(all_models, key=lambda m: m.quality_score)

    def add_provider(
        self,
        provider: ProviderMetadata,
        api_key: Secret,
    ) -> None:
        """Add a new provider at runtime and rebuild internal state."""
        self._providers.append(provider)

        config = AdapterConfig(
            provider_name=provider.name,
            base_url=provider.base_url,
            api_key=api_key,
        )
        self._adapters[provider.name] = OpenAICompatibleAdapter(
            config=config,
            provider=provider,
        )

        self._world_state = WorldState(
            providers=self._providers,
            usage=dict(self._world_state.usage),
            latency=dict(self._world_state.latency),
            health=dict(self._world_state.health),
        )
        self._health_tracker = HealthTracker(
            daily_limits={p.name: p.daily_request_limit for p in self._providers},
        )
        self._planner = Planner(self._world_state)
        self._executor = Executor(
            adapters=self._adapters,
            health_tracker=self._health_tracker,
        )


__all__ = ["LLMClient", "ModelInfo"]
