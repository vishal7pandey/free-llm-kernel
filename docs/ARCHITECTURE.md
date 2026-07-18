# Architecture Specification — Free LLM Inference Kernel

**Document type:** Formal architecture specification  
**Scope:** Design rules, responsibilities, access control, and budgets for the provider-agnostic LLM inference kernel  
**Version:** 0.1.0  
**Date:** 2026-07-18

---

## 1. Design Principles

These principles are the lens through which every design decision is evaluated. A change that violates a principle must either be rejected or elevate a principle to a higher level of abstraction.

| # | Principle | Implication |
|---|-----------|-------------|
| P1 | **Pure Core** | The Core layer has no side effects, no I/O, no network access, and no mutable state. It is a pure data and contract layer. |
| P2 | **Planner is deterministic** | Given the same `WorldState` and `Request`, the Planner always produces the same `ExecutionPlan`.
| P3 | **Runtime is the only network layer** | No other layer may open sockets, make HTTP calls, or read remote state. |
| P4 | **Everything is replaceable through composition** | No concrete class is hard-coded into another layer. Dependencies are injected through interfaces. |
| P5 | **Provider-specific logic never leaks into Core** | Provider naming, API quirks, and endpoint details are confined to adapter implementations in Runtime. |
| P6 | **One request, one execution plan, one terminal state** | Each `trace_id` has exactly one plan and reaches exactly one terminal state. |
| P7 | **Extensions cannot change correctness, only behavior around it** | Middleware and extensions may log, cache, scrub, or measure, but cannot alter the semantics of `Request` or `Response`. |
| P8 | **Every failure is observable** | Every terminal failure leaves a structured trace containing the cause, the layer, and the recovery path attempted. |
| P9 | **Graceful degradation is preferred over catastrophic failure** | If the best path fails, the system falls back through a chain. If all fail, it returns a deterministic error, not a crash. |
| P10 | **Adding a provider requires implementing one adapter** | No Core, Planner, or Extension code changes when a new provider is added. |

---

## 2. System Mission

> Given a normalized user request and a zero-paid budget, return a correct, safe, and timely LLM response by selecting and executing the best currently available free provider, without the user needing to know which provider answered.

### Mission Attributes

| Attribute | Target | Failure Mode |
|-----------|--------|--------------|
| Correctness | Output matches user intent and format contract | Wrong answer, wrong format, missing content |
| Availability | ≥ 99.9% of valid requests reach a terminal state | Hang, crash, ambiguous state |
| Economy | Zero paid spend per request; free-tier quotas respected | Billing event, rapid quota exhaustion |
| Privacy | No credential or PII leakage | Key exposure, prompt egress to untrusted party |
| Latency | p99 < 30s for non-streaming; first token < 5s for streaming | Timeout cascade, routing loop |
| Observability | Every request traceable end-to-end | Silent failures, missing logs |
| Evolvability | New provider/model added in < 1 hour | Hard-coded assumptions, brittle interfaces |

### Performance Budgets

| Resource | Budget | Enforcement |
|----------|--------|-------------|
| Kernel memory (per request) | ≤ 10 MB baseline + input/output size | Streaming; generator-based response handling |
| Kernel CPU (per request) | ≤ 50 ms planning + validation overhead | No heavy computation in Core/Planner |
| HTTP timeout | Default 30 s, configurable per request/provider | `TimeoutPolicy` |
| Concurrent requests | Default 100 per process | `ConcurrencyLimiter` |
| Startup time | ≤ 1 s to first usable `LLMClient` | Lazy provider discovery; optional async warmup |
| Disk writes | ≤ 1 per request (usage accounting) | Batched or SQLite WAL writes |

---

## 3. Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Extensions (Layer 4)                     │
│   Logging │ Metrics │ Cache │ Session │ Security │ Plugins  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       Runtime (Layer 3)                      │
│   Provider Adapters │ HTTP Executor │ Retry │ Circuit Breaker │
│   Streaming │ Response Parser │ Usage Accounting             │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ ExecutionPlan
┌─────────────────────────────────────────────────────────────┐
│                       Planner (Layer 2)                      │
│   Provider Registry │ Capability Match │ Scoring │ Quota     │
│   Context Filter │ Fallback Ordering │ Plan Generator        │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ Request
┌─────────────────────────────────────────────────────────────┐
│                        Core (Layer 1)                        │
│   Types │ Contracts │ Errors │ Capabilities │ Validation    │
│   Trace IDs │ Serialization Rules │ Invariants             │
└─────────────────────────────────────────────────────────────┘
```

### Dependency Rules

- **Layer N may depend only on Layer N-1 or lower.**
- **Extensions may depend on Core and Planner interfaces, but never directly on Runtime adapters.**
- **Runtime may depend on Core and Planner output.**
- **Planner may depend only on Core.**
- **Core depends on nothing except the Python standard library and type system.**

---

## 4. Layer 1 — Core

### 4.1 Responsibilities

1. Define all public data types.
2. Define the error taxonomy.
3. Define the capability vocabulary.
4. Validate request integrity.
5. Provide trace ID generation.
6. Enforce serialization rules.
7. Declare invariants as assertions/contracts.

### 4.2 Access Rules

| Access | Allowed | Notes |
|--------|---------|-------|
| Network I/O | **NO** | Core is pure |
| Disk I/O | **NO** | No files, no database |
| Environment variables | **NO** | Config is injected |
| Mutable state | **NO** | All Core types are immutable/frozen |
| Logging | **NO** | Use typed exceptions instead |
| Time | **NO** | No `time.now()` in Core |
| Standard library | Yes | `dataclasses`, `typing`, `enum`, `json` only |

### 4.3 Invariants

- `Request.trace_id` is unique within the process lifetime.
- `Request.messages` is non-empty and well-formed.
- `Response.finish_reason` is from the closed `FinishReason` enum.
- `Response.provider` and `Response.model` are non-empty strings.
- `Capability` values are from the closed `Capability` enum.
- All Core dataclasses are frozen after construction.

### 4.4 Performance Budget

- Object construction: O(1) per field.
- Request validation: O(n) where n = number of messages, ≤ 1 ms for typical inputs.
- Memory: baseline ≤ 1 KB per `Request`/`Response` object.

---

## 5. Layer 2 — Planner

### 5.1 Responsibilities

1. Load the provider registry.
2. Validate provider configuration.
3. Discover and cache provider model lists.
4. Match request capabilities to provider capabilities.
5. Estimate token counts.
6. Score providers and rank candidates.
7. Generate an `ExecutionPlan`.
8. Order fallback chains.

### 5.2 Access Rules

| Access | Allowed | Notes |
|--------|---------|-------|
| Network I/O | **NO** | Discovery results are injected by Runtime on a schedule |
| Disk I/O | Read-only for registry/config | No writes except through injected `StateStore` interface |
| Environment variables | **NO** | Config passed via `PlannerConfig` |
| Mutable state | Internal only | WorldState is read from `StateStore`, not mutated directly |
| Logging | **NO** | Returns structured decisions; Extensions log them |
| Time | Read-only | May read UTC for cache TTL and quota day boundaries |
| Standard library | Yes | No third-party heavy libraries |

### 5.3 Invariants

- `ExecutionPlan.candidates` is non-empty iff at least one configured provider satisfies all required capabilities.
- `ExecutionPlan.candidates` is sorted by score descending, tie-broken deterministically.
- `ExecutionPlan.candidates` contains no duplicates (by provider+model).
- The Planner never makes provider-specific HTTP calls.
- The Planner never mutates `Request`.

### 5.4 Performance Budget

- Planning latency: ≤ 10 ms for ≤ 100 providers.
- Memory: O(providers × models) for in-memory registry.
- No network calls in planning path (cold discovery is async and decoupled).

---

## 6. Layer 3 — Runtime

### 6.1 Responsibilities

1. Construct provider-specific adapters.
2. Execute HTTP requests against selected providers.
3. Enforce timeouts, retries, and circuit breakers.
4. Handle streaming responses.
5. Parse and normalize provider-specific responses.
6. Update usage accounting.
7. Manage terminal states.

### 6.2 Access Rules

| Access | Allowed | Notes |
|--------|---------|-------|
| Network I/O | **YES — only layer** | HTTP/HTTPS to provider endpoints |
| Disk I/O | **NO** except through injected `UsageStore` | No direct file writes |
| Environment variables | **NO** | Secrets passed through `AdapterConfig` |
| Mutable state | Internal only | Circuit breakers, connection pools |
| Logging | **NO** | Return structured events; Extensions handle logging |
| Time | Yes | For timeouts, latency measurement, circuit breaker cooldown |
| Third-party libraries | Yes | `httpx`/`aiohttp`, `openai` SDK for adapters |

### 6.3 Invariants

- Exactly one adapter executes per `trace_id` at any moment.
- Credentials never leave the Runtime layer in errors or logs.
- Every request reaches a terminal state or raises `LLMError`.
- Streaming output is prefix-consistent: concatenated chunks match the full response content (if a full response is later produced).
- Provider adapters implement the same `Adapter` interface.

### 6.4 Performance Budget

- HTTP connection establishment: amortized via connection pool.
- Per-request overhead: ≤ 5 ms before first byte (excluding network).
- Streaming: first token forwarded within 500 ms of provider sending it.
- Retry delay: exponential backoff, 0.5s to 16s, with jitter.

---

## 7. Layer 4 — Extensions

### 7.1 Responsibilities

1. Logging and tracing.
2. Metrics and observability.
3. Usage accounting persistence.
4. Caching.
5. Session/conversation memory.
6. Security (secret redaction, PII scrubbing, prompt guards).
7. Middleware composition.
8. Plugin loading.

### 7.2 Access Rules

| Access | Allowed | Notes |
|--------|---------|-------|
| Network I/O | Only through Runtime | Cache backends, metrics endpoints are optional and explicit |
| Disk I/O | Yes | Logs, usage store, cache, sessions |
| Environment variables | Read-only | For configuring extension behavior |
| Mutable state | Yes | Caches, session stores, metrics counters |
| Logging | **YES — primary logger** | Must redact secrets before emission |
| Time | Yes | For TTLs, metrics timestamps |
| Third-party libraries | Yes | `structlog`, `prometheus-client`, `sqlitedict`, etc. |

### 7.3 Invariants

- Extensions cannot mutate `Request` semantics. They may only transform representation (e.g., redact PII from prompt copy used for logging, but the original prompt sent to Runtime is unchanged).
- Secret redaction runs before any log or metric emission.
- Cache hits do not bypass the Planner; they short-circuit the Runtime with an identical `Response`.
- Middleware order is total and explicit. The default order is: request logging → security scrubbing → cache → planner/runtime → response processing → cache write → metrics → response logging.
- Plugins are loaded in an isolated import context and cannot modify Core types.

### 7.4 Performance Budget

- Logging overhead: ≤ 1 ms per request.
- PII scrubbing: ≤ 5 ms per prompt for typical sizes.
- Cache lookup: ≤ 1 ms (local), ≤ 10 ms (network cache).
- Usage write: ≤ 5 ms with SQLite WAL, batched if possible.

---

## 8. Inter-Layer Interfaces

### 8.1 Core → Planner

```
Request, Capability, ResponseFormat, WorldState → ExecutionPlan
```

### 8.2 Planner → Runtime

```
ExecutionPlan, AdapterRegistry → ExecutionResult
```

### 8.3 Runtime → Core

```
ExecutionResult → Response
```

### 8.4 Extensions ↔ All Layers

Extensions observe and wrap, but do not replace, layer boundaries. They register hooks:

- `on_request(Request) → Request` (may return a copy, not mutate)
- `on_plan(ExecutionPlan) → None`
- `on_execution_start(ExecutionPlan) → None`
- `on_execution_end(Response | Error) → None`
- `on_response(Response) → Response` (may return a copy)

Extensions that mutate any Core field are invalid and must be rejected by the extension loader.

---

## 9. Security Architecture

### 9.1 Threat Model

| Threat | Layer | Control |
|--------|-------|---------|
| API key leakage | Runtime/Extensions | Store keys in `AdapterConfig`; redact in logs/errors |
| Prompt leakage to training | Planner/Extensions | Provider privacy metadata; optional PII scrubber |
| Prompt injection | Extensions | Input guardrails; system prompt isolation |
| Cache poisoning | Extensions | Signed cache keys; TTL; read-only for untrusted |
| Plugin code execution | Extensions | Sandboxed loader; allowlist; optional disable |
| Secret exposure in stack traces | Extensions | Stack trace sanitizer; custom exception formatter |

### 9.2 Secret Handling Rules

1. API keys are never read from `os.environ` inside Core or Planner.
2. Runtime adapters receive keys through `AdapterConfig` objects.
3. The string value of a key is never included in any `str(exception)`, log, metric label, or response.
4. The `Secret` type wraps strings and redacts them by default in `__repr__` and `__str__`.

---

## 10. State Ownership

| State | Owner | Persistence | Lifetime |
|-------|-------|-------------|----------|
| `Request` / `Response` | Core | None (immutable) | Per request |
| `ExecutionPlan` | Planner | None (immutable) | Per request |
| Provider registry | Planner | Config file / discovery cache | Process |
| Provider model lists | Planner (loaded by Runtime) | TTL cache | TTL (e.g., 1 hour) |
| Usage counters | Extensions (UsageStore) | SQLite/file | Daily, process-persistent |
| Latency history | Extensions (Metrics) | In-memory + optional TSDB | Process + TTL |
| Circuit breaker | Runtime | In-memory | Process |
| Health state | Runtime | In-memory | Process |
| Session / conversation | Extensions (SessionStore) | SQLite/memory/Redis | User-defined TTL |
| Cache | Extensions (CacheStore) | Memory/disk/Redis | TTL |

---

## 11. Error Propagation Rules

1. **Core** raises `ValidationError` for malformed inputs.
2. **Planner** raises `PlanningError` when no candidate exists.
3. **Runtime** raises `ExecutionError` for all provider failures, wrapping the provider-specific error.
4. **Extensions** must not raise into the request path unless configured to be fatal.
5. All errors are typed and serializable. They carry:
   - `trace_id`
   - `layer` (Core/Planner/Runtime/Extension)
   - `category` (auth, rate_limit, network, timeout, validation, etc.)
   - `recoverable` (bool)
   - `retryable` (bool)
   - `provider` (if applicable)
   - Safe message (no secrets)

---

## 12. Concurrency Model

### 12.1 Sync Path

- `LLMClient.chat()` is synchronous.
- Runtime uses a connection pool.
- Usage store writes are atomic (file lock or SQLite transaction).

### 12.2 Async Path

- `LLMClient.achat()` is asynchronous.
- Runtime uses `AsyncOpenAI` or `httpx.AsyncClient`.
- Planning remains synchronous and fast (≤ 10 ms).

### 12.3 Thread Safety

- Core types are immutable.
- Planner is stateless; `WorldState` is a snapshot.
- Runtime maintains per-adapter connection pools (thread-safe or per-thread).
- Usage store uses atomic operations (SQLite WAL, file lock, or lock-free in-memory counter with periodic flush).

---

## 13. Evolvability Rules

1. Adding a provider requires:
   - Implementing `Adapter` interface.
   - Adding provider metadata to registry config.
   - No changes to Core, Planner, or Extensions.
2. Adding a capability requires:
   - Extending `Capability` enum in Core.
   - Updating `Planner.capability_match()`.
   - Updating adapters that support it.
3. Adding an extension requires:
   - Implementing `Extension` interface.
   - Registering in middleware chain.
   - No changes to Core.

---

## 14. Non-Goals

This project will **never**:

- **Train or fine-tune models.** This is an inference kernel, not a training framework.
- **Host inference.** We call remote providers; we do not run model weights.
- **Replace LangChain or LlamaIndex.** This is a lower-level abstraction — a routing and execution kernel, not an agent framework.
- **Replace MCP.** Tool calling is supported, but tool execution is the caller's responsibility.
- **Become an agent framework.** No planning loops, no ReAct, no autonomous execution. The kernel executes one request and returns one response.
- **Support non-LLM APIs.** Image generation, embeddings, and audio synthesis are out of scope.
- **Guarantee SLA or uptime.** We depend on free-tier providers with no uptime guarantees. We maximize availability through fallback, not promises.

---

## 15. Complexity Budgets

These limits prevent god-classes and architectural drift. Violations require an ADR.

| Layer | Max LOC/file | Max public methods | Max cyclomatic complexity |
|-------|-------------|-------------------|--------------------------|
| Core | 500 | 20 | 10 |
| Planner | 400 | 15 | 10 |
| Runtime | 600 | 20 | 12 |
| Extensions | 300 | 10 | 8 |
| Client | 350 | 15 | 8 |

Enforcement: CI should run `radon cc` and fail on threshold breach.

---

## 16. Evolution Strategy

| Version | Focus | Key Changes |
|---------|-------|-------------|
| v0.x | Single-process kernel | Core + Planner + Runtime + Extensions, one process, one client |
| v1.0 | Production hardening | Circuit breaker per provider, quota tracking, health checks, structured logging |
| v2.0 | Distributed quotas | Shared quota store (Redis), multi-process WorldState synchronization |
| v3.0 | Plugin marketplace | Third-party adapters, policy plugins, extension discovery |
| v4.0 | Multiple runtimes | gRPC transport, WebSocket streaming, edge-deployed kernel |

---

## 17. Glossary

| Term | Definition |
|------|------------|
| **Kernel** | Core + Planner + Runtime. The minimal deployable unit. |
| **Extension** | Optional behavior added around the kernel. |
| **Adapter** | Provider-specific implementation of the Runtime interface. |
| **WorldState** | Composite of state views (ProviderCatalogue, HealthSnapshot, QuotaSnapshot) used by Planner. |
| **RoutingPolicy** | Strategy that scores candidates — answers "what should execute?" |
| **ExecutionPlan** | Ordered list of candidates plus retry/fallback/timeout policies. |
| **Terminal state** | One of: `Completed`, `Failed`, `Cancelled`, `TimedOut`. |
