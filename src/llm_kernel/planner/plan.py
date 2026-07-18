"""Plan types: Candidate, ExecutionPlan, and routing policies.

These are Planner outputs — they describe what the Planner decided,
not what Core defines.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from llm_kernel.core import (
    Capability,
    KernelError,
    KernelModel,
    Request,
    ValidationError,
)


class PlanningError(KernelError):
    """Raised when the Planner cannot produce a valid ExecutionPlan."""


class Candidate(KernelModel):
    provider: str
    model: str
    score: float
    estimated_tokens: int = 0
    estimated_latency_ms: float = 0.0
    reason: str = ""

    @model_validator(mode="after")
    def _validate_candidate(self) -> Self:
        if self.estimated_tokens < 0:
            raise ValidationError("estimated_tokens must be non-negative")
        if self.estimated_latency_ms < 0:
            raise ValidationError("estimated_latency_ms must be non-negative")
        return self


class FallbackPolicy(KernelModel):
    max_providers: int = 10
    provider_order: Literal["score", "priority", "round_robin"] = "score"


class TimeoutPolicy(KernelModel):
    total_ms: int = 30_000
    connect_ms: int = 10_000
    first_token_ms: int | None = None


class RetryPolicy(KernelModel):
    max_retries: int = 2
    backoff_base_ms: int = 500
    backoff_max_ms: int = 16_000
    retryable_errors: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {
                "rate_limit",
                "timeout",
                "network",
                "server",
            }
        )
    )


class ExecutionPlan(KernelModel):
    trace_id: str
    request: Request
    candidates: list[Candidate]
    fallback_policy: FallbackPolicy = Field(default_factory=FallbackPolicy)
    timeout_policy: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    required_capabilities: frozenset[Capability] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def _validate_plan(self) -> Self:
        if self.trace_id != self.request.trace_id:
            raise ValidationError("ExecutionPlan.trace_id must match Request.trace_id")

        seen: set[tuple[str, str]] = set()
        for candidate in self.candidates:
            key = (candidate.provider, candidate.model)
            if key in seen:
                raise ValidationError(f"Duplicate candidate: {key}")
            seen.add(key)

        return self


__all__ = [
    "PlanningError",
    "Candidate",
    "FallbackPolicy",
    "TimeoutPolicy",
    "RetryPolicy",
    "ExecutionPlan",
]
