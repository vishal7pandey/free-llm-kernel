# ADR-006: Middleware Chain Over Separate Extension Categories

## Status
Accepted

## Context
Extensions serve heterogeneous purposes: logging (passive observer), cache (intercepts
execution), usage store (persists state), security (transforms data). A review suggested
splitting these into Middleware, Observers, Stores, and Plugins. However, at the current
scale, four categories would add complexity without meaningful benefit.

## Decision
Use a single `MiddlewareChain` with an `Extension` Protocol. All extensions implement the
same five hooks: `on_request`, `on_plan`, `on_execution_start`, `on_execution_end`,
`on_response`. Extensions are ordered and errors are caught (non-fatal by default).

Categories emerge through convention, not type system enforcement:
- **Observers** (logging) — read hooks, return inputs unchanged
- **Middleware** (cache, security) — transform inputs/outputs
- **Stores** (usage) — persist data in hooks, don't transform

## Alternatives Considered
1. **Four separate protocols** — type-safe but over-engineered for current scale
2. **Event bus with typed events** — more flexible, but loses ordering guarantees
3. **Decorator pattern** — composable but harder to reason about order

## Consequences
- **Positive:** Single protocol, single chain, simple mental model
- **Positive:** Ordering is explicit and deterministic
- **Positive:** Adding an extension is one class with five methods
- **Negative:** No compile-time distinction between observer and middleware
- **Negative:** If extension count grows large, may need to revisit and split categories
