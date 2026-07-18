# ADR-002: Split WorldState Into Read-Only Views

## Status
Accepted

## Context
`WorldState` was a monolithic dataclass containing `providers`, `usage`, `latency`, and `health`.
As the system grows, it would accumulate `quota`, `privacy`, `cache`, `policies`, `configuration`,
and more — becoming `EverythingState`. This creates tight coupling: the Planner would depend on
everything, even state it doesn't use.

## Decision
Split `WorldState` into focused, read-only views:

- **`ProviderCatalogue`** — static provider/model registry
- **`HealthSnapshot`** — dynamic health status per provider
- **`QuotaSnapshot`** — dynamic usage/latency per provider

`WorldState` remains as a composite for backward compatibility, but new code should accept
individual views via Protocol-based interfaces.

Each view is a frozen dataclass with query methods. No view contains state it doesn't own.

## Alternatives Considered
1. **Keep monolithic WorldState** — simpler today, but grows unbounded
2. **Dependency injection of individual dicts** — too loose, no type safety
3. **Single `StateStore` with typed accessors** — still a god object, just with methods

## Consequences
- **Positive:** Planner only depends on the views it actually uses
- **Positive:** New state categories (cache, privacy) can be added as new views without touching Planner
- **Positive:** Views are individually testable
- **Negative:** Callers must construct/pass multiple objects instead of one
- **Negative:** `WorldState` composite exists for backward compat — should be deprecated over time
