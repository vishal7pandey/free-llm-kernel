# Architecture Decision Records

ADRs capture significant architectural decisions, their context, and consequences.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](adr-001-four-layer-architecture.md) | Four-layer kernel (Core, Planner, Runtime, Extensions) | Accepted |
| [ADR-002](adr-002-worldstate-split-into-views.md) | Split WorldState into read-only views | Accepted |
| [ADR-003](adr-003-policy-extraction-from-planner.md) | Extract RoutingPolicy from Planner | Accepted |
| [ADR-004](adr-004-slim-core.md) | Slim Core to pure types, enums, contracts, validation | Accepted |
| [ADR-005](adr-005-openai-compatible-adapter.md) | Single OpenAI-compatible adapter for all providers | Accepted |
| [ADR-006](adr-006-middleware-over-observer.md) | Middleware chain over separate observer/store/plugin categories | Accepted |

## Format

Each ADR follows:

```
# ADR-NNN: Title

## Status
Accepted | Proposed | Deprecated | Superseded by ADR-NNN

## Context
What problem are we solving? What constraints exist?

## Decision
What did we decide?

## Alternatives Considered
What else was on the table?

## Consequences
What tradeoffs does this create?
```
