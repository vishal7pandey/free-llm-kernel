# ADR-001: Four-Layer Kernel Architecture

## Status
Accepted

## Context
The system needs to abstract multiple free LLM providers behind a single interface.
Providers have different APIs, quotas, reliability characteristics, and capabilities.
The architecture must allow adding providers without modifying core logic, and must
isolate network concerns from pure computation.

## Decision
Adopt a four-layer architecture with strict dependency rules:

```
Extensions (logging, usage, cache, security)
    ↓ depends on
Runtime (adapters, HTTP, retry, circuit breaker, streaming)
    ↓ depends on
Planner (routing, capability matching, scoring, fallback ordering)
    ↓ depends on
Core (types, enums, contracts, validation, errors — pure, no I/O)
```

Rules:
- Each layer may only import from layers below it
- Core is pure: no network, no disk, no env, no mutable state
- Planner is deterministic: same input → same output
- Runtime is the only layer that makes network calls
- Extensions observe but cannot alter correctness

Enforced via `import-linter` in CI.

## Alternatives Considered
1. **Monolithic module** — simpler to start, but becomes unmaintainable as providers grow
2. **Three layers (Core, Runtime, Client)** — Planner logic would end up in Runtime or Client, mixing concerns
3. **Hexagonal architecture** — overkill for this domain; no inbound adapters needed

## Consequences
- **Positive:** Adding a provider requires only a Runtime adapter — no Core/Planner changes
- **Positive:** Core types are stable and testable in isolation
- **Positive:** Layer violations are caught by import-linter
- **Negative:** More files and indirection for simple operations
- **Negative:** Cross-cutting concerns (like logging) require the Extensions layer
