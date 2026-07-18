"""Planner layer: routing, scoring, capability matching, execution plan generation.

The Planner is deterministic and stateless. It receives a Request and a set of
read-only state views and returns an ExecutionPlan. It makes no network calls.

The Planner answers "what can execute?" — it filters providers by capability
and context window. The RoutingPolicy answers "what should execute?" — it
scores and orders the surviving candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from llm_kernel.core import (
    Capability,
    KernelError,
    Message,
    Request,
    UsageRecord,
    ValidationError,
)
from llm_kernel.planner.catalogue import ModelMetadata, ProviderMetadata
from llm_kernel.planner.plan import (
    Candidate,
    ExecutionPlan,
    FallbackPolicy,
    PlanningError,
    RetryPolicy,
    TimeoutPolicy,
)


# ---------------------------------------------------------------------------
# Read-only state views (replaces monolithic WorldState)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderCatalogue:
    """Static, immutable view of configured providers and their models."""

    providers: tuple[ProviderMetadata, ...]

    def __init__(self, providers: list[ProviderMetadata]):
        object.__setattr__(self, "providers", tuple(providers))

    def get(self, name: str) -> ProviderMetadata | None:
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def names(self) -> list[str]:
        return [p.name for p in self.providers]


@dataclass(frozen=True)
class HealthSnapshot:
    """Dynamic health status per provider: 'healthy', 'degraded', 'unhealthy'."""

    status: dict[str, str] = field(default_factory=dict)

    def is_healthy(self, provider: str) -> bool:
        return self.status.get(provider, "healthy") == "healthy"

    def is_available(self, provider: str) -> bool:
        return self.status.get(provider, "healthy") != "unhealthy"


@dataclass(frozen=True)
class QuotaSnapshot:
    """Dynamic quota/usage info per provider."""

    usage: dict[str, UsageRecord] = field(default_factory=dict)
    latency: dict[str, float] = field(default_factory=dict)

    def get_usage(self, provider: str) -> UsageRecord | None:
        return self.usage.get(provider)

    def get_latency(self, provider: str) -> float | None:
        return self.latency.get(provider)


@dataclass(frozen=True)
class WorldState:
    """Composite of all state views. Kept for backward compatibility.

    New code should accept individual views (ProviderCatalogue, HealthSnapshot,
    QuotaSnapshot) via Protocol-based interfaces instead of this monolith.
    """

    providers: tuple[ProviderMetadata, ...]
    usage: dict[str, UsageRecord] = field(default_factory=dict)
    latency: dict[str, float] = field(default_factory=dict)
    health: dict[str, str] = field(default_factory=dict)

    def __init__(
        self,
        providers: list[ProviderMetadata],
        usage: dict[str, UsageRecord] | None = None,
        latency: dict[str, float] | None = None,
        health: dict[str, str] | None = None,
    ):
        object.__setattr__(self, "providers", tuple(providers))
        object.__setattr__(self, "usage", usage or {})
        object.__setattr__(self, "latency", latency or {})
        object.__setattr__(self, "health", health or {})

    @property
    def catalogue(self) -> ProviderCatalogue:
        return ProviderCatalogue(list(self.providers))

    @property
    def health_snapshot(self) -> HealthSnapshot:
        return HealthSnapshot(dict(self.health))

    @property
    def quota_snapshot(self) -> QuotaSnapshot:
        return QuotaSnapshot(usage=dict(self.usage), latency=dict(self.latency))


# ---------------------------------------------------------------------------
# Routing Policy Protocol
# ---------------------------------------------------------------------------


class RoutingPolicy(Protocol):
    """Policy that decides 'what should execute' (vs 'what can execute').

    The Planner determines which providers *can* satisfy a request.
    The policy determines the *ordering* and *scoring* of candidates.
    """

    def score(
        self,
        request: Request,
        provider: ProviderMetadata,
        model: ModelMetadata,
        estimated_tokens: int,
        health: HealthSnapshot,
        quota: QuotaSnapshot,
    ) -> float: ...


class DefaultRoutingPolicy:
    """Balanced scoring: quality + latency + capability match + quota penalty.

    This is the default policy that preserves existing Planner behavior.
    """

    def score(
        self,
        request: Request,
        provider: ProviderMetadata,
        model: ModelMetadata,
        estimated_tokens: int,
        health: HealthSnapshot,
        quota: QuotaSnapshot,
    ) -> float:
        quality = model.quality_score
        latency = model.latency_score

        available_capabilities = provider.capabilities | model.capabilities
        required_count = len(request.capabilities_required)
        matched_count = len(request.capabilities_required & available_capabilities)
        capability_bonus = 0.2 * (matched_count / required_count) if required_count else 0.0

        headroom = model.max_context_tokens / max(estimated_tokens, 1)
        context_score = min(1.0, headroom / 10.0)

        usage = quota.get_usage(provider.name)
        quota_penalty = self._quota_penalty(usage)

        latency_history = quota.get_latency(provider.name)
        latency_bonus = 0.0
        if latency_history is not None:
            latency_bonus = max(0.0, 1.0 - latency_history / 1000.0) * 0.1

        model_match = 0.0
        if request.model and (model.id == request.model or request.model in model.id):
            model_match = 100.0

        priority_tiebreak = -provider.priority * 0.001

        return (
            quality * 0.35
            + latency * 0.20
            + capability_bonus
            + context_score * 0.05
            - quota_penalty
            + latency_bonus
            + model_match
            + priority_tiebreak
        )

    def _quota_penalty(self, usage: UsageRecord | None) -> float:
        if usage is None or usage.request_count <= 0:
            return 0.0
        return min(0.3, usage.request_count * 0.01)


class FastestPolicy:
    """Prioritize latency above all else."""

    def score(
        self,
        request: Request,
        provider: ProviderMetadata,
        model: ModelMetadata,
        estimated_tokens: int,
        health: HealthSnapshot,
        quota: QuotaSnapshot,
    ) -> float:
        base = model.latency_score
        latency_history = quota.get_latency(provider.name)
        if latency_history is not None:
            base += max(0.0, 1.0 - latency_history / 1000.0) * 0.3
        if request.model and model.id == request.model:
            base += 100.0
        return base


class CheapestPolicy:
    """Prioritize lowest cost above all else."""

    def score(
        self,
        request: Request,
        provider: ProviderMetadata,
        model: ModelMetadata,
        estimated_tokens: int,
        health: HealthSnapshot,
        quota: QuotaSnapshot,
    ) -> float:
        total_cost = model.cost_per_1k_input + model.cost_per_1k_output
        score = 1.0 / (1.0 + total_cost)
        if request.model and model.id == request.model:
            score += 100.0
        return score


class QualityPolicy:
    """Prioritize model quality above all else."""

    def score(
        self,
        request: Request,
        provider: ProviderMetadata,
        model: ModelMetadata,
        estimated_tokens: int,
        health: HealthSnapshot,
        quota: QuotaSnapshot,
    ) -> float:
        score = model.quality_score
        if request.model and model.id == request.model:
            score += 100.0
        return score


# ---------------------------------------------------------------------------
# Token Estimation
# ---------------------------------------------------------------------------


class TokenEstimator(Protocol):
    """Protocol for token estimation."""

    def estimate_messages(self, messages: list[Message]) -> int: ...


class DefaultTokenEstimator:
    """Fallback token estimator using character count / 4.

    This is intentionally crude. Production should use a per-model tokenizer
    or tiktoken when available, injected via the TokenEstimator protocol.
    """

    CHARS_PER_TOKEN = 4

    def estimate_messages(self, messages: list[Message]) -> int:
        total = 0
        for message in messages:
            total += self.estimate_content(message.content)
        return max(1, total)

    def estimate_content(self, content: str | list[Any]) -> int:
        if isinstance(content, str):
            return max(1, len(content) // self.CHARS_PER_TOKEN)

        count = 0
        for part in content:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                count += max(1, len(text) // self.CHARS_PER_TOKEN)
            else:
                count += 256
        return max(1, count)

    def estimate(self, text: str) -> int:
        """Estimate tokens for a plain string."""
        return max(1, len(text) // self.CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """Deterministic planner that converts a Request and state views into an ExecutionPlan.

    The Planner answers 'what can execute?' — it filters providers by capability
    and context window. The RoutingPolicy answers 'what should execute?' — it
    scores and orders the surviving candidates.
    """

    def __init__(
        self,
        world_state: WorldState,
        token_estimator: TokenEstimator | None = None,
        policy: RoutingPolicy | None = None,
    ):
        self._world_state = world_state
        self._token_estimator = token_estimator or DefaultTokenEstimator()
        self._policy = policy or DefaultRoutingPolicy()

    def plan(self, request: Request, world_state: WorldState | None = None) -> ExecutionPlan:
        """Generate an ExecutionPlan for the given Request.

        Args:
            request: The normalized request.
            world_state: Optional override of the planner's default world state.

        Returns:
            ExecutionPlan with ordered candidates.

        Raises:
            PlanningError: If no provider can satisfy the request.
        """
        state = world_state or self._world_state
        estimated_tokens = self._token_estimator.estimate_messages(request.messages)

        health = state.health_snapshot
        quota = state.quota_snapshot

        candidates: list[Candidate] = []
        for provider in state.providers:
            for model in provider.models:
                candidate = self._evaluate(request, provider, model, estimated_tokens, health, quota)
                if candidate is not None:
                    candidates.append(candidate)

        if not candidates:
            required = sorted(request.capabilities_required)
            raise PlanningError(
                f"No provider satisfies capabilities {required} "
                f"and context window for {estimated_tokens} tokens"
            )

        candidates.sort(key=lambda c: (-c.score, c.provider, c.model))

        return ExecutionPlan(
            trace_id=request.trace_id,
            request=request,
            candidates=candidates,
            fallback_policy=FallbackPolicy(),
            timeout_policy=TimeoutPolicy(total_ms=request.timeout_ms),
            retry_policy=RetryPolicy(),
            required_capabilities=request.capabilities_required,
        )

    def _evaluate(
        self,
        request: Request,
        provider: ProviderMetadata,
        model: ModelMetadata,
        estimated_tokens: int,
        health: HealthSnapshot,
        quota: QuotaSnapshot,
    ) -> Candidate | None:
        """Evaluate a (provider, model) pair. Return None if it cannot satisfy the request."""
        available_capabilities = provider.capabilities | model.capabilities
        if not request.capabilities_required.issubset(available_capabilities):
            return None

        if estimated_tokens > model.max_context_tokens:
            return None

        if not health.is_available(provider.name):
            return None

        score = self._policy.score(request, provider, model, estimated_tokens, health, quota)

        return Candidate(
            provider=provider.name,
            model=model.id,
            score=score,
            estimated_tokens=estimated_tokens,
            estimated_latency_ms=quota.get_latency(provider.name) or 0.0,
            reason=self._reason(request, provider, model, score),
        )

    def _reason(
        self,
        request: Request,
        provider: ProviderMetadata,
        model: ModelMetadata,
        score: float,
    ) -> str:
        parts = [f"provider={provider.name}", f"model={model.id}"]
        if request.model and model.id == request.model:
            parts.append("user-requested-model")
        parts.append(f"score={score:.3f}")
        return ", ".join(parts)


__all__ = [
    "TokenEstimator",
    "DefaultTokenEstimator",
    "WorldState",
    "ProviderCatalogue",
    "HealthSnapshot",
    "QuotaSnapshot",
    "RoutingPolicy",
    "DefaultRoutingPolicy",
    "FastestPolicy",
    "CheapestPolicy",
    "QualityPolicy",
    "Planner",
    "PlanningError",
    "Candidate",
    "ExecutionPlan",
    "FallbackPolicy",
    "TimeoutPolicy",
    "RetryPolicy",
    "ModelMetadata",
    "ProviderMetadata",
]
