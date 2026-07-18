# ADR-003: Extract RoutingPolicy From Planner

## Status
Accepted

## Context
The Planner originally contained both routing logic (which providers *can* satisfy a request)
and scoring policy (which candidates *should* be preferred). This conflates two distinct
concerns. As policies evolve (fastest, cheapest, quality, privacy, research, interactive),
embedding them in Planner would cause it to grow unbounded.

## Decision
Separate responsibilities:

- **Planner** answers "what can execute?" — filters by capability, context window, health
- **RoutingPolicy** answers "what should execute?" — scores and orders surviving candidates

`RoutingPolicy` is a Protocol with a single `score()` method. Built-in implementations:
- `DefaultRoutingPolicy` — balanced (quality + latency + capability + quota)
- `FastestPolicy` — prioritize latency
- `CheapestPolicy` — prioritize cost
- `QualityPolicy` — prioritize quality

Users can implement custom policies and inject them into the Planner.

## Alternatives Considered
1. **Strategy pattern with enum** — less flexible, can't add custom scoring
2. **Policy as config dict** — not type-safe, hard to validate
3. **Multiple Planner subclasses** — duplicates filtering logic

## Consequences
- **Positive:** Planner stays small and focused on filtering
- **Positive:** Policies are independently testable
- **Positive:** Users can inject custom policies at runtime
- **Negative:** One more abstraction to understand
- **Negative:** Policy receives many parameters (request, provider, model, tokens, health, quota)
