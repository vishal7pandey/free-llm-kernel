# ADR-004: Slim Core to Pure Types, Enums, Contracts, Validation

## Status
Accepted

## Context
Core originally contained provider metadata, model metadata, candidate types, execution plans,
and policies — in addition to pure data types (Message, Request, Response, Usage). This made
Core a dependency sink: any change to provider catalogue structure or plan format required
changing Core, which should be the most stable layer.

## Decision
Reduce Core to:
- **Types:** Message, Request, Response, Usage, UsageRecord
- **Enums:** Role, Capability, FinishReason, ResponseFormatType, ErrorCategory, PrivacyLevel
- **Contracts:** KernelModel base, Secret wrapper
- **Validation:** ValidationError, KernelError, ExecutionError
- **Utility:** generate_trace_id

Moved to Planner layer:
- `ProviderMetadata`, `ModelMetadata` → `planner/catalogue.py`
- `Candidate`, `ExecutionPlan`, `FallbackPolicy`, `TimeoutPolicy`, `RetryPolicy` → `planner/plan.py`
- `PlanningError` → `planner/plan.py`

## Alternatives Considered
1. **Keep everything in Core** — simpler imports, but Core becomes unstable
2. **Move to a separate `types` package** — adds a fifth layer, unnecessary indirection
3. **Put metadata in config.py** — mixes static data with runtime configuration

## Consequences
- **Positive:** Core is minimal and maximally stable
- **Positive:** Provider catalogue changes don't ripple through Core
- **Positive:** Clear ownership: planner types live where planner logic lives
- **Negative:** Import paths change — `from llm_kernel.core import X` → `from llm_kernel.planner import X`
- **Negative:** Top-level `__init__.py` must re-export for backward compatibility
