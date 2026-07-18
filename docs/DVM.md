# Design Verification Matrix (DVM) — Free LLM Inference Kernel

**Version:** 0.1.0  
**Scope:** Maps every architecture requirement, invariant, and failure mode control to a test strategy.  
**Date:** 2026-07-18

---

## 1. How to Read This Matrix

| Column | Meaning |
|--------|---------|
| **ID** | Unique requirement/invariant identifier |
| **Artifact** | Source document (`ARCHITECTURE`, `INTERFACE`, `STATE`, `DFMEA`) |
| **Requirement / Invariant** | The statement to verify |
| **Verification Method** | Test category: Unit, Integration, Property, Concurrency, Fuzz, Manual, Static |
| **Test Strategy** | How to verify it |
| **Acceptance Criteria** | Pass/fail condition |
| **Priority** | Must / Should / Could |

---

## 2. Core Layer Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| C-01 | ARCHITECTURE | Core has no network I/O, disk I/O, env access, mutable state, logging, or time calls | Static | Static analysis / import linter | No `requests`, `urllib`, `open`, `os.getenv`, `logging`, `time` imports in `core/` | Must |
| C-02 | ARCHITECTURE | `Request.trace_id` is unique within process lifetime | Property | Generate 10,000 `Request` objects; check uniqueness | No collisions across 10,000 requests | Must |
| C-03 | INTERFACE | `Request.messages` is non-empty and well-formed | Unit | Construct valid and invalid `Request` objects | `ValidationError` raised for empty/malformed messages | Must |
| C-04 | INTERFACE | `temperature` is `None` or in `[0.0, 2.0]` | Unit | Parametrize boundary and out-of-range values | Values `[-0.1, 2.1, 5.0]` are rejected; `[0.0, 0.7, 2.0]` accepted | Must |
| C-05 | INTERFACE | `max_tokens` is `None` or `> 0` | Unit | Test `-1, 0, 1, None` | Negative and zero rejected | Must |
| C-06 | INTERFACE | `Response.finish_reason` is from closed enum | Unit | Construct `Response` with invalid `finish_reason` | `ValidationError` raised | Must |
| C-07 | INTERFACE | All Core types round-trip through JSON without data loss | Unit | `to_json(from_json(x)) == x` for all Core types | Equality preserved for all sample objects | Must |
| C-08 | INTERFACE | `__repr__` of Core types redacts secrets and truncates long content | Unit | Create `Request` with long content and `AdapterConfig` with `Secret` | `Secret` shown as `***`; content > 200 chars truncated | Must |
| C-09 | INTERFACE | `Capability` and `FinishReason` are closed enums | Static | Enum membership tests | New values cannot be added at runtime | Should |
| C-10 | DFMEA-C-05 | All errors are serializable and typed | Unit | Serialize all `ExecutionError` variants to JSON | Round-trip preserves category, recoverable, retryable, safe message | Must |
| C-11 | DFMEA-C-07 | `Message` multi-modal content validates URL/base64 formats | Unit | Pass invalid `image_url` and malformed base64 | `ValidationError` raised for invalid content | Should |

---

## 3. Planner Layer Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| P-01 | ARCHITECTURE | Planner makes no network calls | Static | Mock `httpx` / ban `requests` in `planner/` | Import linter + unit tests with no network mocks needed | Must |
| P-02 | ARCHITECTURE | `ExecutionPlan.candidates` non-empty ⇔ satisfiable | Unit | Provide requests that match 0, 1, and many providers | Empty plan for unsatisfiable; non-empty for satisfiable | Must |
| P-03 | ARCHITECTURE | `ExecutionPlan.candidates` sorted by score descending | Unit | Create providers with known scores; plan | Candidate order matches expected descending score | Must |
| P-04 | ARCHITECTURE | No duplicate `(provider, model)` pairs in plan | Unit | Inject registry with duplicate model aliases | Plan deduplicates | Must |
| P-05 | ARCHITECTURE | Planner never mutates `Request` | Unit | Pass frozen `Request`; call `plan()`; assert identity/equality | `Request` unchanged after planning | Must |
| P-06 | INTERFACE | `ExecutionPlan.trace_id` matches `Request.trace_id` | Unit | Generate plan from request | Match verified | Must |
| P-07 | DFMEA-P-04 | Capabilities filter providers correctly | Unit | Request `CAPABILITY_TOOLS` with only tool-supporting providers | Non-tool providers excluded from plan | Must |
| P-08 | DFMEA-P-04 | Context window filtering skips providers with insufficient context | Unit | Request with 100k tokens; providers with 8k and 128k context | Only 128k provider in plan | Must |
| P-09 | DFMEA-P-05 | Quota-aware scoring ranks providers with more remaining quota higher | Unit | Configure Groq at 100% usage, Google at 50% | Google ranked above Groq | Should |
| P-10 | DFMEA-P-08 | Token estimation prevents context-length routing mistakes | Integration | Use tiktoken or equivalent; estimate tokens for long prompt | Estimate within ±10% of provider-reported usage | Should |
| P-11 | DFMEA-P-09 | Model discovery refreshes stale model lists | Integration | Mock `/models` endpoint returning new/removed models | Registry updated after TTL | Could |
| P-12 | DFMEA-P-02 | Invalid API keys detected at startup | Integration | Configure provider with invalid key; run health check | Provider marked `UNHEALTHY` before planning | Must |

---

## 4. Runtime Layer Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| R-01 | ARCHITECTURE | Runtime is the only layer with network I/O | Static | Import linter + code review | Only `runtime/` contains `httpx`/`openai`/socket usage | Must |
| R-02 | ARCHITECTURE | Exactly one adapter executes per `trace_id` at any moment | Concurrency | Launch 100 concurrent requests; trace provider calls | No `trace_id` has overlapping provider calls | Must |
| R-03 | ARCHITECTURE | Credentials never leave Runtime layer in errors or logs | Integration | Force 401/403/500 errors from mock provider | Error message contains no API key substring | Must |
| R-04 | ARCHITECTURE | Every request reaches terminal state or raises `LLMError` | Property | Generate random valid requests against mock providers | All return `Response` or raise `LLMError` | Must |
| R-05 | ARCHITECTURE | Streaming output is prefix-consistent | Integration | Stream from mock provider; compare concatenated chunks to full response | `''.join(chunks) == response.content` | Must |
| R-06 | INTERFACE | `Response.provider` and `Response.model` identify actual executor | Integration | Mock two providers; run request | `Response` matches the provider that actually executed | Must |
| R-07 | DFMEA-R-01 | Default HTTP timeout (30s) is enforced | Integration | Mock server hangs for 60s | `TimeoutError` raised within ~30s | Must |
| R-08 | DFMEA-R-04 | Retry on transient 502/503 with exponential backoff | Integration | Mock provider returns 503 twice, then 200 | Request succeeds after 2 retries; delays increase exponentially | Must |
| R-09 | DFMEA-R-05 | Do not retry 401/403 errors | Integration | Mock provider returns 401 | No retry; provider skipped/failed immediately | Must |
| R-10 | DFMEA-R-06 | Streaming failure handled without crashing caller | Integration | Mock stream drops after 5 chunks | Caller receives partial chunks + structured error or fallback | Must |
| R-11 | DFMEA-R-08 | Non-OpenAI-compatible response normalized to `Response` | Integration | Mock provider returns unexpected JSON | `Response` constructed; malformed fields handled | Must |
| R-12 | DFMEA-R-09 | `content == None` handled (finish_reason checked) | Integration | Mock provider returns `content: null` with `finish_reason: "content_filter"` | `Response.content = None`; `finish_reason` preserved | Should |
| R-13 | DFMEA-R-10 | Circuit breaker opens after N consecutive failures | Unit | Configure failure threshold; fail provider N times | Provider excluded from subsequent plans; half-open after cooldown | Must |
| R-14 | DFMEA-R-11 | Concurrent usage file writes are atomic | Concurrency | Run 50 threads incrementing usage simultaneously | Final count equals number of increments; file not corrupted | Must |
| R-15 | STATE | Request state machine transitions are valid | Property | Model check / fuzz state transitions | Only allowed transitions occur; terminal states absorbing | Should |

---

## 5. Extension Layer Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| E-01 | ARCHITECTURE | Extensions cannot mutate `Request` semantics | Unit | Write extension that tries to mutate `Request` | `ExtensionError` or copy returned; original unchanged | Must |
| E-02 | ARCHITECTURE | Secret redaction runs before any log/metric emission | Integration | Force an error path; capture logs and metrics | No API key found in captured output | Must |
| E-03 | ARCHITECTURE | Middleware order is total and explicit | Unit | Register extensions out of order; verify execution order | Order matches registration; security extension before logging | Must |
| E-04 | INTERFACE | `Extension.on_response` may return a copy, not mutate | Unit | Extension returns modified `Response` copy | Original `Response` unchanged | Should |
| E-05 | DFMEA-E-04 | API keys redacted in error messages | Unit | Construct `ExecutionError` with key in message; run redaction | Output contains `"***"` or empty where key was | Must |
| E-06 | DFMEA-E-05 | Optional PII scrubber removes sensitive data from logs | Integration | Send prompt with fake SSN/credit card; log it | Log contains `[REDACTED]` or masked value | Should |
| E-07 | DFMEA-E-08 | Cache hit produces same `Response` as live call | Integration | Call once; call again with identical request | Second call returns cached response; content identical | Should |
| E-08 | DFMEA-E-09 | Session memory persists multi-turn context | Integration | Create session; send two messages; inspect sent messages | Both user and assistant messages in subsequent request | Could |

---

## 6. Cross-Layer Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| X-01 | ARCHITECTURE | Layer N depends only on Layer N-1 or lower | Static | Import graph analysis (e.g., `import-linter`) | No forbidden imports (Runtime → Planner allowed; Planner → Runtime forbidden) | Must |
| X-02 | DFMEA-EM-01 | Retry storm prevented across concurrent clients | Concurrency | Simulate 100 concurrent requests with failing provider | Total attempts bounded by `concurrency × max_retries` | Should |
| X-03 | DFMEA-EM-03 | Routing oscillation prevented by score smoothing | Integration | Two providers with similar scores; alternate latency measurements | Candidate order stable within tolerance | Could |
| X-04 | DFMEA-EM-04 | Thundering herd on newly discovered model prevented | Concurrency | Simulate burst to one provider; enforce token bucket | Requests processed at provider RPM limit, not faster | Should |
| X-05 | STATE | `COMPLETED`, `FAILED`, `TIMED_OUT`, `CANCELLED` are absorbing | Property | After terminal state, attempt disallowed transitions | State machine raises `InvalidStateTransition` | Must |
| X-06 | DFMEA-R-04 | Streaming fails but usage not double-counted | Integration | Start stream; fail after 3 chunks; retry on fallback | Usage incremented only for the successful/final provider | Must |

---

## 7. Security Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| S-01 | ARCHITECTURE | API keys never read from `os.environ` in Core/Planner | Static | Search `os.getenv`/`os.environ` in `core/` and `planner/` | Zero matches except in tests | Must |
| S-02 | ARCHITECTURE | `Secret` type redacts in `__repr__` and `__str__` | Unit | `repr(secret)` and `str(secret)` | Output does not contain actual key | Must |
| S-03 | DFMEA-SEC-03 | Prompt injection guardrails reject or log suspicious input | Integration | Send known jailbreak prompts | Guardrail triggers; action logged or blocked | Could |
| S-04 | DFMEA-SEC-06 | Output validation catches harmful content (if configured) | Integration | Mock provider returning flagged content | Output filter triggers | Could |

---

## 8. Performance Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| PERF-01 | ARCHITECTURE | Kernel memory per request ≤ 10 MB baseline + I/O | Load | Send 100 requests with 1k tokens; monitor RSS | No request path allocates > 10 MB beyond input/output | Should |
| PERF-02 | ARCHITECTURE | Planning latency ≤ 10 ms for ≤ 100 providers | Benchmark | Generate 100 providers; measure `plan()` time | p99 < 10 ms | Should |
| PERF-03 | ARCHITECTURE | Streaming first token forwarded within 500 ms of provider sending | Integration | Mock server emits first chunk immediately; measure time to first yield | < 500 ms | Should |
| PERF-04 | ARCHITECTURE | Disk writes ≤ 1 per request | Benchmark | Count `UsageStore.increment` calls | One increment per successful request | Must |

---

## 9. Evolvability Verification

| ID | Artifact | Requirement / Invariant | Method | Test Strategy | Acceptance Criteria | Priority |
|----|----------|------------------------|--------|-----------------|---------------------|----------|
| EV-01 | ARCHITECTURE | Adding provider requires only new adapter + registry entry | Manual | Add a fake provider adapter without modifying Core/Planner/Extensions | `LLMClient` works with new provider | Must |
| EV-02 | ARCHITECTURE | Adding capability requires Core + Planner update, no Runtime forced change | Manual | Add ` Capability.AUDIO_OUTPUT`; update Planner | Existing adapters still compile/run | Should |
| EV-03 | INTERFACE | Public API (`LLMClient.chat`) remains stable across minor versions | Static | Semver API compatibility check | No breaking changes to `chat` signature in minor versions | Should |

---

## 10. Test Coverage Targets

| Layer | Unit | Integration | Concurrency | Property | Fuzz | Target Coverage |
|-------|------|-------------|-------------|----------|------|-----------------|
| Core | High | Low | None | Medium | Low | 95% |
| Planner | High | Medium | Low | High | Medium | 90% |
| Runtime | High | High | High | Medium | High | 85% |
| Extensions | Medium | High | Medium | Low | Low | 80% |
| Cross-layer | Low | High | High | High | High | 70% |

---

## 11. Test Infrastructure

### Required Tools

| Tool | Purpose |
|------|---------|
| `pytest` | Unit and integration tests |
| `pytest-asyncio` | Async test support |
| `pytest-xdist` | Parallel/concurrency tests |
| `hypothesis` | Property-based tests |
| `aresponses` / `respx` | HTTP mocking |
| `import-linter` | Layer dependency checks |
| `mypy` / `pyright` | Static type checking |
| `bandit` | Security static analysis |
| `locust` or `k6` | Load tests (optional) |

### CI/CD Verification

Every PR must pass:

1. `mypy --strict` on `core/` and `planner/`
2. `import-linter` layer checks
3. Unit test suite (≥ 95% Core coverage)
4. Integration test suite with mocked providers
5. Concurrency test suite for usage store and runtime
6. Bandit security scan

---

## 12. Example Test Cases

### Example: Circuit Breaker (R-13)

```python
import pytest

@pytest.mark.parametrize("failures", [3, 4, 5])
def test_circuit_breaker_opens_after_threshold(runtime, failures):
    for _ in range(failures):
        with pytest.raises(ExecutionError):
            runtime.execute(plan_with_provider("mock-failing"))

    # After threshold, provider should be skipped without network call
    result = runtime.plan(Request(...))  # Should not include mock-failing
    assert "mock-failing" not in [c.provider for c in result.candidates]
```

### Example: Secret Redaction (E-05)

```python
def test_error_message_does_not_contain_api_key():
    err = ExecutionError(
        trace_id="t1",
        provider="groq",
        category=ErrorCategory.AUTH,
        message=f"Invalid key: {GROQ_API_KEY}",
        recoverable=True,
        retryable=False,
    )
    safe = redact_secrets(err)
    assert GROQ_API_KEY not in safe.message
    assert "***" in safe.message
```

### Example: Request State Machine (X-05)

```python
def test_terminal_state_absorbing(request):
    sm = RequestStateMachine(request)
    sm.transition_to("COMPLETED")
    with pytest.raises(InvalidStateTransition):
        sm.transition_to("EXECUTING")
```

---

## 13. Risk-Based Test Priority

### Must (block release)

- C-01, C-03, C-04, C-05, C-06, C-07, C-08
- P-01, P-02, P-03, P-04, P-05
- R-01, R-02, R-03, R-04, R-05, R-07, R-10, R-13, R-14
- E-01, E-02, E-03
- X-01, X-06
- S-01, S-02

### Should (high priority)

- C-09, C-10, C-11
- P-06, P-07, P-08, P-12
- R-06, R-08, R-09, R-11, R-12, R-15
- E-04, E-05, E-07
- X-02, X-05
- PERF-01, PERF-02, PERF-04

### Could (nice to have)

- P-09, P-10, P-11
- R-15
- E-06, E-08
- X-03, X-04
- S-03, S-04
- PERF-03
- EV-01, EV-02, EV-03
