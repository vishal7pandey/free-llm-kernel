"""Provider and model catalogue types.

These are registry data, not Core types. They live in the Planner layer
because they describe what the Planner reasons about.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from llm_kernel.core import Capability, KernelModel, PrivacyLevel, ValidationError


class ModelMetadata(KernelModel):
    id: str
    display_name: str
    max_context_tokens: int
    max_output_tokens: int | None = None
    capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    quality_score: float = 0.5
    latency_score: float = 0.5

    @model_validator(mode="after")
    def _validate_model_metadata(self) -> Self:
        if self.max_context_tokens <= 0:
            raise ValidationError("max_context_tokens must be positive")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValidationError("max_output_tokens must be positive")
        for score in (self.quality_score, self.latency_score):
            if not (0.0 <= score <= 1.0):
                raise ValidationError("quality_score and latency_score must be between 0.0 and 1.0")
        if any(c < 0 for c in (self.cost_per_1k_input, self.cost_per_1k_output)):
            raise ValidationError("costs must be non-negative")
        return self


class ProviderMetadata(KernelModel):
    name: str
    display_name: str
    adapter_type: str
    base_url: str
    api_key_env: str
    models: list[ModelMetadata]
    default_model: str
    priority: int = 0
    capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    privacy_level: PrivacyLevel = PrivacyLevel.UNKNOWN
    daily_request_limit: int | None = None

    @model_validator(mode="after")
    def _validate_provider_metadata(self) -> Self:
        if not self.models:
            raise ValidationError(f"Provider {self.name!r} must have at least one model")
        model_ids = {m.id for m in self.models}
        if self.default_model not in model_ids:
            raise ValidationError(
                f"default_model {self.default_model!r} not in models for provider {self.name!r}"
            )
        return self


__all__ = ["ModelMetadata", "ProviderMetadata"]
