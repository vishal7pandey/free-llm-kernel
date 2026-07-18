# DFMEA v2 — Architecture-Driven Failure Analysis

## Inference Operating System (IOS) for Free LLM Providers

**Document Type:** Design FMEA with Fault Tree, Invariants, and Cross-Product Analysis  
**Scope:** Not implementation-specific; applies to the *class* of minimal, provider-agnostic LLM inference kernels  
**Architecture:** Four immutable layers — Core, Planner, Runtime, Extensions  
**Date:** 2026-07-18

---

## 1. System Mission

> **Mission Statement:**  
> Given a normalized user request and zero paid budget, convert it into a correct, safe, and timely LLM response using the best currently available free provider, without the user ever needing to know which provider answered.

### Mission Attributes (success criteria)

| Attribute | Definition | Failure Means |
|-----------|-----------|---------------|
| **Correctness** | Output matches user intent and format contract | Wrong answer, wrong format, missing content |
| **Availability** | Request receives a terminal response (success or deterministic error) | Hang, crash, ambiguous state |
| **Economy** | Never spends money; respects free-tier quotas | Billing event, quota exhaustion too fast |
| **Privacy** | User data is not leaked to unauthorized parties | API key exposure, prompt leakage, PII egress |
| **Latency** | Response arrives within acceptable wall time | Timeout, cascading fallback delays |
| **Observability** | Every request leaves an understandable audit trail | Silent failures, no traceability |
| **Evolvability** | New providers/models can be added without kernel changes | Hard-coded assumptions, brittle interfaces |

---

## 1.5 Design Principles

These principles are the invariant lens through which every future design decision is evaluated. A proposed change that violates a principle must either be rejected or cause the principle to be elevated to a higher level of abstraction.

| # | Principle | Why It Matters | Failure Mode If Violated |
|---|-----------|----------------|--------------------------|
| **P1** | **Pure Core** — the Core layer has no side effects, no I/O, no network access, and no mutable state. | Keeps the contract layer testable, portable, and free from provider-specific drift. | Core types become entangled with runtime behavior; unit tests require network mocks. |
| **P2** | **Planner is deterministic** — given the same `WorldState` and `Request`, the Planner always produces the same `ExecutionPlan`. | Enables reproducible routing decisions, caching, and debugging. | Flaky routing; unreproducible bugs; cache invalidation becomes impossible. |
| **P3** | **Runtime is the only networking layer.** | Security boundary: credentials and network calls never leak into Core/Planner/Extensions. | Secrets appear in logs; planners make unauthorized HTTP calls; testing becomes fragile. |
| **P4** | **Everything is replaceable through composition.** | No concrete class is hard-coded into another layer. Dependencies are injected through interfaces. | Kernel becomes a monolith; swapping a provider or store requires code surgery. |
| **P5** | **Provider-specific logic never leaks into Core.** | Naming, quirks, and endpoint details live only in adapter implementations. | Core becomes a patchwork of special cases; adding providers requires Core changes. |
| **P6** | **One request, one execution plan, one terminal state.** | Each `trace_id` has exactly one plan and reaches exactly one terminal outcome. | Duplicate executions, lost requests, or ambiguous success/failure states. |
| **P7** | **Extensions cannot change correctness—only behavior around it.** | Middleware may log, cache, scrub, or measure, but cannot alter `Request`/`Response` semantics. | A logging extension silently changes routing decisions or output content. |
| **P8** | **Every failure is observable.** | Every terminal failure leaves a structured trace containing cause, layer, and recovery path. | Silent failures; impossible to diagnose routing or provider outages. |
| **P9** | **Graceful degradation is preferred over catastrophic failure.** | If the best path fails, fall back. If all fail, return a deterministic error rather than crash. | User application crashes; partial stream outputs become uncaught exceptions. |
| **P10** | **Adding a provider requires implementing one adapter.** | No Core, Planner, or Extension code changes when a new provider is added. | Adding providers becomes a multi-file refactor; the system stops evolving. |

### Principle-to-DFMEA Mapping

| Principle | Protects Against | Relevant DFMEA Categories |
|-----------|----------------|---------------------------|
| P1, P3 | Side-effect contamination, secret leakage | Security, Provider, Execution |
| P2, P6 | Non-deterministic routing, duplicate execution | Routing, State Machine, Reliability |
| P4, P5, P10 | Architectural rot, provider lock-in | Extensibility, Configuration, Evolution |
| P7 | Middleware bugs altering behavior | Extensions, Observability |
| P8, P9 | Silent failures and crashes | Observability, Resilience, Reliability |

---

## 2. Architectural Layers (4-Layer Kernel)

Everything in the system belongs to exactly one of these four layers. This is **MECE**.

### Layer 1: Core
**Responsibility:** Define the language of the system. Nothing in Core makes network calls, persists state, or knows about providers.

- Request/response types
- Errors and exceptions
- Capabilities catalog
- Invariants
- Contracts (pre/post conditions)
- Serialization rules

### Layer 2: Planner
**Responsibility:** Decide *what* to execute, *where*, and *when*. No side effects.

- Provider discovery
- Capability matching
- Quota/latency/quality scoring
- Execution plan generation
- Fallback ordering

### Layer 3: Runtime
**Responsibility:** Execute the plan. This is the only layer that talks to the network.

- Provider adapters
- HTTP execution
- Streaming
- Retry and circuit breaking
- Response parsing

### Layer 4: Extensions
**Responsibility:** Add behavior through composition. Optional. Can be swapped without touching the kernel.

- Observability (logging, metrics, tracing)
- Persistence (usage store, conversation memory, cache)
- Security (prompt sanitization, PII scrubbing, key management)
- Middleware
- Plugin system

---

## 3. Failure Taxonomy (MECE Categories)

Every failure mode in the system maps to exactly one leaf of this tree.

```
Failure
├── Functional Correctness
│   ├── Wrong answer
│   ├── Wrong format
│   ├── Missing content
│   ├── Partial content
│   └── Contract violation
├── Emergent Behavior
│   ├── Oscillation
│   ├── Thundering herd
│   ├── Retry storm
│   ├── Provider flapping
│   ├── Routing bias
│   └── Deadlock/livelock
├── State Machine
│   ├── Invalid transition
│   ├── Missing transition
│   ├── Race condition
│   ├── Impossible state
│   └── Terminal state not reached
├── Information Failure
│   ├── Wrong metadata
│   ├── Wrong capability
│   ├── Wrong quota
│   ├── Wrong latency
│   ├── Wrong token estimate
│   ├── Wrong provider health
│   └── Wrong API version
├── Resource Failure
│   ├── Memory exhaustion
│   ├── Thread starvation
│   ├── Connection pool exhaustion
│   ├── Socket exhaustion
│   ├── Disk/IO saturation
│   ├── Rate limit (provider-side)
│   └── CPU saturation
├── Distributed Failure
│   ├── Clock skew
│   ├── Split brain
│   ├── Duplicate execution
│   ├── Network partition
│   ├── Partial write
│   ├── Lost acknowledgement
│   ├── DNS poisoning
│   └── TLS/cert failure
├── Human Failure
│   ├── Wrong API key
│   ├── Wrong configuration
│   ├── Wrong routing policy
│   ├── Wrong model
│   ├── Wrong middleware order
│   ├── Wrong plugin
│   └── Wrong environment
└── Evolution Failure
    ├── Provider removes model
    ├── Provider changes API
    ├── Provider changes limits/pricing
    ├── Capability changes
    ├── New provider appears
    └── Old provider dies
```

---

## 4. Layer Contracts and Invariants

### 4.1 Core Contracts

#### Type: `Request`
```python
@dataclass
class Request:
    messages: list[Message]
    model: str | None          # user preference, not resolved
    capabilities_required: set[Capability]
    response_format: ResponseFormat
    max_tokens: int | None
    temperature: float | None
    timeout_ms: int
    stream: bool
    metadata: dict            # extension passthrough
    trace_id: str
```

**Preconditions:**
- `messages` is non-empty and well-formed.
- `temperature` is `None` or in `[0.0, 2.0]`.
- `max_tokens` is `None` or `> 0`.

**Postconditions:**
- `Request` is immutable after creation.
- `trace_id` is globally unique (or collision-probable enough).

#### Type: `Response`
```python
@dataclass
class Response:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: FinishReason
    provider: str
    model: str
    usage: Usage
    latency_ms: float
    trace_id: str
    metadata: dict
```

**Postconditions:**
- `finish_reason` is one of `{completed, length, content_filter, tool_calls, error, cancelled}`.
- `usage` contains `prompt_tokens`, `completion_tokens`, `total_tokens` if provided by provider; otherwise `None`.
- `provider` and `model` identify the actual executor.

#### Type: `ExecutionPlan`
```python
@dataclass
class ExecutionPlan:
    request: Request
    candidates: list[Candidate]   # ordered by score descending
    fallback_policy: FallbackPolicy
    timeout_policy: TimeoutPolicy
    retry_policy: RetryPolicy
    required_capabilities: set[Capability]
```

**Invariant:**
> `ExecutionPlan.candidates` is non-empty if and only if at least one configured provider can satisfy `required_capabilities`.

### 4.2 Global Invariants

| ID | Invariant | Violation Examples |
|----|-----------|-------------------|
| I-01 | **Exactly one provider executes per request.** | Zero providers (lost request). Two providers (double execution). |
| I-02 | **Every request reaches exactly one terminal state.** | Completed AND Failed. Stuck in Executing forever. |
| I-03 | **No paid provider is ever selected when a free one is sufficient.** | Selects OpenAI GPT-4 when Groq is available. |
| I-04 | **Provider credentials never leave the Runtime layer.** | Key leaked in error message, log, or response. |
| I-05 | **Usage accounting is monotonic per provider per day.** | Count goes backward. Double-count one request. |
| I-06 | **Routing decisions are reproducible given the same state.** | Same request routed differently with no state change. |
| I-07 | **Streaming output is a prefix of the final response.** | Final content contradicts streamed chunks. |
| I-08 | **The planner never makes network calls.** | Planner queries provider model list directly. |
| I-09 | **Extensions cannot alter Core contracts.** | Middleware changes Request type shape. |
| I-10 | **The system degrades gracefully when all providers fail.** | Crash. Infinite loop. Unhandled exception. |

---

## 5. Main DFMEA Worksheet

Columns: **Function → Requirement → Failure Mode → Local Effect → Next Higher Effect → End Effect → Detection → Prevention → Recovery → Residual Risk (RPN)**

### Layer 1: Core

| ID | Function | Requirement | Failure Mode | Local Effect | Next Higher Effect | End Effect | Detection | Prevention | Recovery | Residual Risk |
|----|----------|-------------|--------------|--------------|-------------------|------------|-----------|------------|----------|---------------|
| C-01 | Define `Request` type | `messages` must be well-formed | User passes malformed message list | `Request` created with invalid shape | Planner cannot normalize | Provider returns 400, fallback loop, or crash | JSON Schema validation | Pydantic/attrs validation with strict types | Reject request before planning | Medium |
| C-02 | Define `Request` type | `temperature` in valid range | User passes `temperature=5.0` | Invalid parameter stored | Runtime sends invalid param to provider | Provider 400, fallback | Range validation at construction | Clamp or reject out-of-range values | Clamp at runtime as fallback | Low |
| C-03 | Define `Response` type | `finish_reason` always set | Provider omits `finish_reason` | `Response` has `None` finish_reason | Caller can't detect truncation | User gets incomplete answer, no warning | Schema validation | Define `finish_reason` defaults per provider | Infer from `max_tokens` vs actual tokens | Medium |
| C-04 | Define capability catalog | Capabilities are mutually exclusive and exhaustive | Capability not in catalog | Planner ignores unknown capability | Provider selected that doesn't support feature | Feature fails silently (e.g. JSON mode returns plain text) | Capability whitelist | Versioned capability enum | Reject unknown capabilities at planning | Medium |
| C-05 | Define errors | All errors are serializable and typed | Custom exception loses context | Error message only contains string | Caller cannot programmatically recover | User sees generic error | Typed exception hierarchy | All Runtime errors wrap with `ProviderError`, `RoutingError`, etc. | Map provider errors to typed errors | High |
| C-06 | Enforce contracts | Preconditions checked at layer boundaries | Layer ignores preconditions | Invalid state propagates downstream | Planner/Runtime acts on bad data | Wrong provider/model selected, wrong response | Contract assertions in debug builds | Pydantic validators, runtime assertions | Fail fast with descriptive error | High |
| C-07 | Serialization | Request serializes to provider-specific format | Unknown content type in message | Serialization fails | Runtime cannot construct body | 400 or exception | Content-type validation | Define `Message` union (text/image/audio) | Reject unsupported content | Medium |
| C-08 | Trace IDs | Every request has unique trace ID | Trace ID collision | Two requests appear as one | Logs/metrics conflated | Cannot debug failures | UUIDv7 / ULID generation | Generate trace IDs with sufficient entropy | Include nanosecond timestamp + random | Low |

### Layer 2: Planner

| ID | Function | Requirement | Failure Mode | Local Effect | Next Higher Effect | End Effect | Detection | Prevention | Recovery | Residual Risk |
|----|----------|-------------|--------------|--------------|-------------------|------------|-----------|------------|----------|---------------|
| P-01 | Discover providers | Know configured providers and their models | API key invalid but marked configured | Provider included in candidate list | Runtime gets 401/403 | Request fails, fallback to next | Startup health check | Validate keys at load time with test ping | Mark provider unhealthy, skip | High |
| P-02 | Discover providers | Models are current | Provider removed a model | Plan includes dead model | Runtime gets 404 | Fallback, wasted latency | Periodic `/models` refresh | Cache with TTL; live discovery fallback | Mark model unavailable on first 404 | Medium |
| P-03 | Capability match | Select providers that support required capabilities | Capability metadata stale | Provider lacks claimed capability | Request sent to incompatible provider | Feature fails or 400 | Capability validation at request time | Test capabilities during provider onboarding; version metadata | Filter out on mismatch | High |
| P-04 | Capability match | Route long context to suitable provider | No token estimation | 100k prompt sent to 8k-context provider | Provider rejects or truncates | Wrong/partial answer, wasted quota | Token counter (tiktoken, provider tokenizer) | Estimate tokens before planning; store `max_context` per model | Skip providers with `max_context < estimated_input` | Critical |
| P-05 | Score providers | Best provider has highest score | Scoring ignores quota | Provider with 1 request left ranked first | Provider exhausted immediately | Slower fallback, quota waste | Quota tracking | Score = f(health, latency, quota_remaining, capability_match, quality) | Re-plan on 429 | High |
| P-06 | Score providers | Latency history accurate | Latency samples stale | Slow provider ranked first | User waits longer | Poor UX, timeout | Per-provider latency histogram with decay | Recency-weighted EMA; outlier rejection | Timeout policy triggers re-plan | Medium |
| P-07 | Generate plan | Candidate list is non-empty | No provider satisfies requirements | `ExecutionPlan.candidates == []` | Runtime has nothing to execute | User gets "no provider" error | Precondition invariant (I-01) | Check candidate list before returning plan | Return actionable error: which requirements blocked | Medium |
| P-08 | Fallback ordering | Fallback order is sound (best first, rest as backup) | Fallback order reverses on tie | Worse provider tried first | User gets lower quality | Wrong answer quality | Deterministic tie-breaker (priority, then name, then latency) | Document and test ordering rules | Re-score after each failed attempt | Medium |
| P-09 | Quota-aware routing | Don't select exhausted providers | Usage state stale across processes | Process A doesn't see process B's usage | Quota exceeded on provider | 429 errors, slower fallbacks | Shared state (SQLite/redis/filelock) | Atomic usage store with file lock or SQLite WAL | Read latest state before each plan | High |
| P-10 | Quality routing | Prefer higher-quality models for complex prompts | No complexity estimation | Simple prompt routed to expensive frontier model | Wastes quota on easy task | Quota exhausted faster | Prompt complexity classifier (optional) | Default to cheap model; escalate if complexity high | User can override model/provider | Low |

### Layer 3: Runtime

| ID | Function | Requirement | Failure Mode | Local Effect | Next Higher Effect | End Effect | Detection | Prevention | Recovery | Residual Risk |
|----|----------|-------------|--------------|--------------|-------------------|------------|-----------|------------|----------|---------------|
| R-01 | Adapter construction | Build provider-specific client | Base URL malformed (e.g. missing CF_ACCOUNT_ID) | Client cannot connect | Connection error | Fallback or hard failure | URL template validation | Validate all placeholders filled at construction | Mark provider unhealthy, skip | High |
| R-02 | Adapter construction | Use correct credentials per provider | Credentials swapped between providers | Groq key sent to Google | 401/403 | Request fails, key may be logged | Client isolation per provider | Store credentials in provider-scoped adapter | Health check catches auth errors | Critical |
| R-03 | HTTP execution | Request completes within timeout | No timeout configured | Request hangs indefinitely | Thread blocks forever | Application freezes | Set default timeout (e.g. 30s) | Pass `timeout` to HTTP client | Cancel and fall back | Critical |
| R-04 | HTTP execution | Retry transient errors | No retry on 502/503 | Single transient failure escalates to fallback | Worse provider used unnecessarily | Lower quality/availability | Retry policy for idempotent operations | Exponential backoff, max 3 retries | Mark provider unhealthy after retries | High |
| R-05 | HTTP execution | Don't retry non-idempotent or auth errors | Retry on 401/403 | Keys leaked in retries or banned | Rate limit / account lock | Service unavailable | Error classification | Do not retry auth errors; retry only 429/502/503/timeout | Log and skip provider | Medium |
| R-06 | Streaming | Deliver chunks as they arrive | Connection drops mid-stream | Generator raises exception | Caller receives partial output and traceback | User sees broken stream | Try/except inside generator | Wrap `_stream()` in error boundary; yield error sentinel or raise structured exception | For non-stream, fall back to next provider | Critical |
| R-07 | Streaming | Final response matches stream | Provider sends different content in non-stream endpoint | Inconsistency | User confused | N/A (separate path) | Compare streamed and final outputs in tests | Use same endpoint for both | Document limitation | Low |
| R-08 | Response parsing | Extract content, tool calls, usage, finish reason | Provider returns non-OpenAI-compatible JSON | Pydantic validation fails | Runtime cannot parse response | Unhandled exception | Response schema validation | Adapter maps provider-specific response to `Response` type | Return raw response + error for debugging | High |
| R-09 | Response parsing | Handle empty or null content | `content` is `None` | Returns empty string | User thinks model was silent | Check `content` and `finish_reason` | `finish_reason == "content_filter"` indicates filtering | Differentiate null vs empty vs filtered | Retry on next provider if unexpected | Medium |
| R-10 | Circuit breaker | Don't call unhealthy providers | No circuit breaker | Dead provider attempted every request | Wasted time, unnecessary fallbacks | Latency, timeout | Track consecutive failures per provider | Open circuit after N failures; half-open after cooldown | Skip provider until healthy | High |
| R-11 | Concurrency | Multiple requests don't corrupt state | No locking around shared usage file | Concurrent writes corrupt `.usage.json` | Usage counts wrong, over-quota | Billing/rate-limit | File locking or SQLite | Use atomic writes or SQLite WAL with transactions | Rebuild usage file from backup | High |
| R-12 | Concurrency | Thread-safe access to clients | Shared OpenAI client mutated | Race condition in connection pool | Sporadic failures | Hard to reproduce | Thread-safe HTTP client design | Don't mutate clients; create per-thread if needed | Document thread safety | Medium |

### Layer 4: Extensions

| ID | Function | Requirement | Failure Mode | Local Effect | Next Higher Effect | End Effect | Detection | Prevention | Recovery | Residual Risk |
|----|----------|-------------|--------------|--------------|-------------------|------------|-----------|------------|----------|---------------|
| E-01 | Logging | Every request logged with trace_id | Logger not configured | No output, or excessive output | Cannot debug failures | Silent failures | Structured logging with levels | Default to INFO for routing, DEBUG for extension detail | Log to stderr + file by default | Medium |
| E-02 | Metrics | Track per-provider usage/latency/errors | Metrics counted wrong | Wrong provider appears healthy | Bad routing decisions | Cascade failure | Metrics validation tests | Use atomic counters; separate success/failure/latency | Alert on anomalous metrics | High |
| E-03 | Usage store | Persist usage across restarts | Store file deleted | Quota counters reset | Quota overuse | 429s, slower fallbacks | Backup / multiple storage backends | SQLite with WAL; cloud sync optional | Warn on missing file, reinitialize | Medium |
| E-04 | Security — secrets | Never leak API keys | Error messages include raw request | Key printed to log or returned to user | Account compromise | Audit failure | Regex scrubber for keys in logs | Central secret redaction in logging extension | Encrypt usage store | Critical |
| E-05 | Security — PII | Don't send PII to untrusted providers | No prompt sanitizer | Sensitive data sent to provider that trains on it | Privacy violation, compliance issue | Regulatory/legal risk | PII detector extension | Optional regex/NER scanning; provider privacy metadata | Warn/block for high-risk providers | High |
| E-06 | Security — prompt injection | Prevent jailbreak/prompt injection | No input validation | Malicious prompt causes unwanted output | System instruction leak, harmful content | Reputation/legal risk | Prompt classifier / guardrails | System prompt isolation; input/output filters | Log and block suspicious prompts | Medium |
| E-07 | Middleware | Middleware runs in defined order | Order undefined or wrong | Logging happens after sanitization (leaks PII) | Secret/PII leak | Audit failure | Middleware chain builder | Explicit ordered list; validation tests | Document default order | High |
| E-08 | Cache | Don't return stale cached responses | Cache key ignores model/temperature | Same response for different parameters | Wrong answer | User gets stale/incorrect output | Cache key includes all deterministic inputs | Include model, messages hash, temperature, max_tokens, response_format in key | TTL + invalidation | Medium |
| E-09 | Conversation memory | Maintain multi-turn context | Memory lost across requests | Each request is stateless | User must resend context | Bad UX, higher token usage | Session store | SQLite/memory/redis session backend | Warn if session not found | Low |
| E-10 | Plugin loader | Load plugins safely | Untrusted plugin executes arbitrary code | Code injection | System compromise | Malware | Plugin sandbox / import restrictions | Load plugins from known paths; validate signatures | Disable plugin system by default | Medium |

---

## 6. Cross-Product Analysis

Failures often arise from **interactions** between layers. Below is a matrix of high-risk cross-layer failure combinations.

### 6.1 Cross-Layer Interaction Matrix

| Interaction | Failure | Local Effect | End Effect | Risk |
|-------------|---------|--------------|------------|------|
| **Planner + State** | Quota stale → bad plan | Plan selects exhausted provider | 429 → fallback | High |
| **Planner + Runtime** | Latency score ignores current load | Plan sends burst to one fast provider | Provider throttles all requests | High |
| **Runtime + Extensions** | Logging captures request before secret scrubber | API key written to log file | Credential leak | Critical |
| **Core + Runtime** | `Request` allows `max_tokens` > provider limit | Runtime gets context-length error | Fallback or truncation | Medium |
| **Extensions + Extensions** | Cache stores response before PII scrubber | Cached response contains PII | Repeated PII leakage | Critical |
| **Planner + Core** | Capability catalog missing new capability | Plan ignores valid providers | Suboptimal routing | Medium |
| **Runtime + State** | Streaming fails but usage already incremented | Quota consumed for failed stream | Premature quota exhaustion | High |
| **Extensions + Runtime** | Middleware timeout shorter than Runtime timeout | Middleware cancels successful request | User gets timeout despite provider succeeding | Medium |
| **Core + Planner** | Trace ID collision in high-throughput system | Two requests share logs/metrics | Debugging impossible | Medium |

### 6.2 Emergent Failure Modes

| ID | Name | Description | Trigger | Mitigation |
|----|------|-------------|---------|------------|
| EM-01 | **Retry Storm** | Multiple clients retry same dead provider simultaneously | Provider outage + no shared circuit breaker | Circuit breaker + jittered exponential backoff |
| EM-02 | **Provider Flapping** | Provider alternates healthy/unhealthy rapidly | Intermittent 429/500 | Hysteresis on health state; cooldown periods |
| EM-03 | **Routing Oscillation** | Planner switches between two providers due to stale latency | Two providers have similar scores | Smoothing (EMA) + score tie-breaker |
| EM-04 | **Thundering Herd** | Many requests hit the newly-discovered free model at once | Model goes viral in free tier | Token bucket / concurrency limit per provider |
| EM-05 | **Quota Skew** | One provider's quota exhausted faster because it's always ranked first | Priority-only routing | Quota-aware scoring with diminishing returns |
| EM-06 | **Stream-Fallback Gap** | Once streaming starts, fallback impossible | Streaming design doesn't buffer | Pre-flight health check + buffered stream with error recovery |

---

## 7. Fault Tree Analysis

### Top Event

> **TE: User did not receive the correct answer.**

```
TE: User did not receive the correct answer.
│
├── OR: No response returned
│   ├── AND: Request never reached Runtime
│   │   ├── Request validation failed
│   │   ├── Planner produced empty candidate list
│   │   └── Middleware rejected request
│   ├── AND: Runtime failed to execute
│   │   ├── All providers exhausted
│   │   ├── All providers timed out
│   │   ├── All providers returned unrecoverable error
│   │   └── Streaming failed and no recovery
│   └── AND: Response not delivered to user
│       ├── Response parsing failed
│       ├── Extension crashed
│       └── Connection to caller lost
│
├── OR: Wrong response returned
│   ├── Wrong provider/model selected
│   │   ├── Capability mismatch
│   │   ├── Context window exceeded
│   │   └── Quality/routing score wrong
│   ├── Prompt corrupted in transit
│   │   ├── Encoding issue
│   │   ├── Message format mismatch
│   │   └── System prompt injection
│   ├── Response content incorrect
│   │   ├── Model hallucination (outside system control)
│   │   ├── Truncated output
│   │   └── Tool call not parsed
│   └── Format contract violated
│       ├── JSON mode not enforced
│       ├── Schema validation skipped
│       └── Wrong MIME type
│
└── OR: Response returned too late
    ├── Routing too slow
    │   ├── Too many fallback attempts
    │   └── Slow provider selected
    ├── Execution too slow
    │   ├── Provider latency high
    │   ├── Retry storm
    │   └── Timeout too generous
    └── Extension overhead
        ├── Logging blocks
        ├── Cache miss + slow fetch
        └── PII scan blocks
```

### Minimal Cut Sets (top 10)

A **cut set** is a set of leaf events that together cause the top event.

| Cut Set ID | Leaf Events | Interpretation |
|------------|-------------|----------------|
| CS-01 | `Planner empty candidate list` | No provider matches requirements |
| CS-02 | `All providers exhausted` + `All providers timed out` | Quota and network both fail |
| CS-03 | `Wrong provider/model selected` | Single point routing mistake |
| CS-04 | `Capability mismatch` + `No fallback` | Feature unsupported and no backup |
| CS-05 | `Streaming failed` + `No stream recovery` | Live response unrecoverable |
| CS-06 | `Response parsing failed` + `Extension crashed` | Got response but couldn't deliver |
| CS-07 | `JSON mode not enforced` + `Schema validation skipped` | Wrong format silently accepted |
| CS-08 | `Too many fallback attempts` + `Slow provider selected` | Latency death spiral |
| CS-09 | `Logging blocks` + `Timeout too generous` | Observable but unusable |
| CS-10 | `PII scan blocks` + `Cache miss` | Privacy correctness but poor availability |

---

## 8. State Machine Analysis

### 8.1 Request Lifecycle States

```
[Idle]
  │
  ▼
[Validating] ──(invalid)──▶ [Rejected]
  │
  ▼
[Planning] ──(no candidates)──▶ [NoProvider]
  │
  ▼
[Selecting]
  │
  ▼
[Executing]
  │
  ├──(success)──────────────▶ [Completed]
  │
  ├──(retry same provider)──▶ [Executing]
  │
  ├──(fallback)─────────────▶ [Selecting]
  │
  └──(all failed)───────────▶ [Failed]
```

### 8.2 Invalid / Missing / Race-prone Transitions

| # | Invalid Transition | Why It Happens | Control |
|---|-------------------|---------------|---------|
| 1 | `Executing → Planning` (re-plan during execution) | Mid-execution score update changes candidate list | Freeze plan once execution starts; re-plan only after terminal state |
| 2 | `Completed → Executing` | Success callback triggers another execution | Idempotent terminal states; reject transitions from terminal states |
| 3 | `Failed → Selecting` | Retry loop doesn't terminate | Max fallback attempts; distinguish retry from fallback |
| 4 | `Selecting → Selecting` (infinite) | Fallback chain has cycle | Enforce candidate uniqueness; detect loop |
| 5 | `Executing → Executing` same provider > N times | Retry storm | Max retries per provider per request |
| 6 | `Idle → Completed` | Cached response returned without validation | Validate cache hit against request before terminal state |
| 7 | `Validating → Executing` | Skip planning | Strict state machine; no shortcuts |
| 8 | `Completed AND Failed` | Concurrent status updates | Terminal state mutex; only one terminal outcome per trace_id |

---

## 9. Architecture Invariants (Refined)

| Layer | Invariant | Enforcement Point |
|-------|-----------|-------------------|
| Core | `Request.trace_id` is unique within process lifetime | Factory function |
| Core | `Response.finish_reason` is from closed enum | Response constructor |
| Planner | `ExecutionPlan.candidates` non-empty ⇔ satisfiable | Post-plan validation |
| Planner | Candidates sorted by score descending | Sort after scoring |
| Runtime | Only one adapter executes at a time per trace_id | Executor state |
| Runtime | Credentials never cross layer boundary | Adapter encapsulation |
| Runtime | Every request reaches terminal state or raises `LLMError` | Executor finally block |
| Extensions | Middleware order is total and explicit | Builder validation |
| Extensions | Secrets redacted before any log/metric emission | Logging extension scrubber |
| Extensions | Usage increments monotonically | Atomic store operation |

---

## 10. Functional Decomposition (MECE) — 4 Layers

### Core Functions
1. Define request/response contracts
2. Define error taxonomy
3. Define capability vocabulary
4. Validate request integrity
5. Serialize/deserialize messages
6. Generate trace IDs

### Planner Functions
1. Load provider registry
2. Validate provider configuration
3. Discover/refresh provider models
4. Match capabilities to requirements
5. Estimate token count
6. Score providers
7. Generate execution plan
8. Order fallback chain

### Runtime Functions
1. Construct provider adapters
2. Execute HTTP request
3. Manage timeouts
4. Retry transient failures
5. Stream responses
6. Parse provider-specific responses
7. Update circuit breaker
8. Account for usage
9. Handle terminal states

### Extension Functions
1. Log requests/responses
2. Emit metrics
3. Persist usage
4. Sanitize secrets
5. Detect PII/prompt injection
6. Cache responses
7. Manage sessions
8. Load plugins

---

## 10. Failure Category Deep-Dive

### 10.1 Functional Correctness Failures

| Failure | Root Cause | Detection | Mitigation |
|---------|-----------|-----------|------------|
| Wrong answer | Wrong model for task; prompt misinterpreted | Response quality heuristics; user feedback | Capability-aware model selection; prompt templates |
| Wrong format | `response_format` ignored or unsupported | Schema validation on output | Filter providers by format support; validate output |
| Missing content | `finish_reason == "length"` or content filter | Check finish reason | Retry with higher max_tokens or different provider |
| Partial content | Streaming interrupted; tool call not returned | Compare streamed vs final | Buffer stream; validate tool call parsing |
| Contract violation | Provider returns non-standard response | Response schema validation | Adapter normalization layer |

### 10.2 Information Failures

| Failure | Example | Control |
|---------|---------|---------|
| Wrong capability | Claims tool calling, doesn't support it | Capability test suite per provider/model |
| Wrong quota | Counter stale; limit changed | Live quota headers + persisted counters + env overrides |
| Wrong latency | Outdated latency samples | Recency-weighted histogram; timeout overrides |
| Wrong token estimate | Using wrong tokenizer | Per-model tokenizer mapping; fallback to byte-count |
| Wrong health | Provider flapping | Hysteresis + backoff on health transitions |
| Wrong API version | Provider endpoint changed | Versioned adapter config; health checks |

### 10.3 Resource Failures

| Resource | Failure Mode | Mitigation |
|----------|-------------|------------|
| Memory | Large prompts/outputs in memory | Streaming; generator-based processing |
| Threads | Thread pool exhaustion | Async runtime; limit concurrency per provider |
| Connections | Connection pool saturation | `AsyncOpenAI` with shared httpx client; limits |
| Sockets | Too many open sockets | TCP connection reuse; timeouts |
| Disk | Usage log grows unbounded | Rotation; prune old data |
| Rate limits | Provider-side 429 | Token bucket client-side; backoff; fallback |

### 10.4 Distributed Failures

| Failure | Effect | Mitigation |
|---------|--------|------------|
| Clock skew | Usage day boundaries misaligned | Use UTC; attribute usage at request start |
| Duplicate execution | Same request sent twice | Idempotency key per trace_id; dedupe on provider side if supported |
| Network partition | Client can't reach provider | Timeout + fallback; circuit breaker |
| Partial write | `.usage.json` corrupted | Atomic writes; SQLite WAL; backup/restore |
| Lost ack | Don't know if provider processed request | Idempotency; safe-to-retry classification |
| DNS poisoning | Connect to wrong server | DNS over HTTPS; certificate pinning |
| TLS cert expiry | Connection refused | Monitor cert expiry; fail open to next provider |

### 10.5 Human Failures

| Failure | Example | Mitigation |
|---------|---------|------------|
| Wrong API key | Key pasted with trailing space | Validation at startup; test ping |
| Wrong config | `CF_ACCOUNT_ID` missing | Required field validation |
| Wrong routing policy | User forces exhausted provider | Warn; allow override with confirmation |
| Wrong model | `model="gpt-4"` on free-only system | Validate against free model list |
| Wrong middleware order | Logging before sanitization | Builder with enforced default order |
| Wrong plugin | Untrusted plugin loaded | Code signing; allowlist; sandbox |
| Wrong environment | `.env` from dev used in prod | Environment-specific config; validation |

### 10.6 Evolution Failures

| Failure | Example | Mitigation |
|---------|---------|------------|
| Provider removes model | `llama-3.3-70b-versatile` deprecated | `/models` discovery; graceful degradation |
| Provider changes API | New auth flow | Versioned adapters; health checks |
| Provider changes limits | Free tier reduced | Configurable limits; live headers |
| Capability changes | Model no longer supports vision | Capability refresh; filter |
| New provider appears | Miss opportunity | Plugin-based provider discovery |
| Old provider dies | All keys become useless | Multi-provider fallback; alerts |

---

## 11. Design Actions (Prioritized)

### Phase A: Kernel Correctness (must have)

1. **Define Core types with Pydantic/attrs** — strict validation, versioned schemas.
2. **Implement 4-layer separation** — no network calls in Planner, no side effects in Core.
3. **Add trace IDs and structured logging** — minimum observability.
4. **Implement typed error hierarchy** — every failure maps to a recoverable category.
5. **Add token estimation** — prevent context-window failures.
6. **Add capability metadata per provider/model** — enable capability-aware routing.

### Phase B: Resilience (should have)

7. **Circuit breaker per provider** — stop trying dead providers.
8. **Retry with exponential backoff and jitter** — handle transient errors.
9. **Timeout policies at request and provider level** — prevent hangs.
10. **Atomic usage store (SQLite or filelock)** — prevent corruption and support concurrency.
11. **Streaming error boundary** — catch mid-stream failures cleanly.
12. **Response schema validation** — normalize provider outputs.

### Phase C: Intelligence (nice to have)

13. **Live `/models` discovery** with TTL cache.
14. **Latency history with recency weighting**.
15. **Quota-aware scoring** — don't burn scarce providers first.
16. **Quality scoring** — route complex prompts to stronger models.
17. **Middleware system** with ordered hooks.
18. **Plugin interface** for custom providers.

### Phase D: Production Hardening (for shared/long-running)

19. **Async runtime** (`achat`, `astream`).
20. **OpenAI-compatible server mode** (`/v1/chat/completions`).
21. **Metrics export** (Prometheus/OpenTelemetry).
22. **PII/prompt injection guardrails**.
23. **Secret redaction** in all logs/errors.
24. **Cache with proper invalidation**.

---

## 12. Comparison: Code-Level vs. Architecture-Level DFMEA

| Aspect | DFMEA v1 (Code) | DFMEA v2 (Architecture) |
|--------|----------------|------------------------|
| Focus | `llm.py` as implemented | Class of minimal LLM inference kernels |
| Granularity | Line-by-line failures | Layer/function/requirement failures |
| Format | Component → Failure | Mission → Function → Requirement → Failure → Effects → Detection → Prevention → Recovery → Residual Risk |
| Count | 87 failure modes | 40 representative; framework scales to 1,000+ |
| Includes | Code-specific bugs | Cross-product, emergent, state machine, distributed, evolution failures |
| Deliverables | RPN table, fix priority | Architecture invariants, contracts, fault tree, cut sets, design actions |
| Use case | Fix current wrapper | Design next-generation kernel |

---

## 13. Recommended Next Step

The current `llm.py` is a **Phase A proof-of-concept**. To evolve it into the architecture described here:

1. **Refactor into 4 packages:** `core/`, `planner/`, `runtime/`, `extensions/`.
2. **Rewrite `LLMClient` as a composition** of `Planner` + `Executor` + `UsageStore` + `Logger`.
3. **Keep the public API stable** (`LLMClient.chat(...)`), but internals become architecture-driven.
4. **Add one extension at a time** starting with logging + SQLite usage store.

This preserves the "legendary, minimal, lightweight" goal while making the system resilient enough to survive the constant churn of free LLM providers.
