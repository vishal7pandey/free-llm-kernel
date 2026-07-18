# Interface Specification — Free LLM Inference Kernel

**Version:** 0.1.0  
**Scope:** All public types, their fields, invariants, serialization rules, equality, and lifecycle.  
**Date:** 2026-07-18

---

## 1. Core Types

All Core types are immutable. They may be implemented with `frozen=True` dataclasses, `pydantic.BaseModel` (frozen), or equivalent. They must support:

- Deep equality (`__eq__` and `__hash__` consistent)
- JSON serialization (`to_json` / `from_json`) round-trip without loss
- String representation that redacts secrets and truncates long content

---

## 1.1 `Message`

```python
@frozen
class Message:
    role: Role
    content: str | list[ContentPart]
    name: str | None = None
    metadata: dict = field(default_factory=dict)
```

### Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `role` | `Role` | Yes | One of `system`, `user`, `assistant`, `tool` |
| `content` | `str` or `list[ContentPart]` | Yes | Plain text or multi-modal content parts |
| `name` | `str \| None` | No | Tool or participant name |
| `metadata` | `dict` | No | Opaque key-value passthrough |

### Invariants

- `role` is from the closed `Role` enum.
- `content` is non-empty if `role == "user"`.
- If `content` is a list, at least one `ContentPart` exists.
- `ContentPart` discriminated union: `TextPart`, `ImagePart`, `AudioPart`.

### Serialization

```json
{
  "role": "user",
  "content": "Hello!",
  "metadata": {}
}
```

or multi-modal:

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "What is in this image?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
  ]
}
```

### Lifecycle

- Created by user or session store.
- Passed unchanged through Core, Planner, and Runtime adapter normalization.
- Destroyed with `Response` (if session is not persisted).

---

## 1.2 `Role` (Enum)

```python
class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
```

- Closed set. No extension.

---

## 1.3 `ContentPart`

```python
@frozen
class ContentPart:
    type: str  # "text", "image_url", "audio_url", "image_base64", "audio_base64"
    # type-specific fields follow
```

### Invariants

- `type` is from the closed union.
- For `image_url`/`audio_url`, the URL must be a valid `https://` or `data:` URL.
- For `*_base64` types, the data field must be valid base64.

---

## 1.4 `Request`

```python
@frozen
class Request:
    trace_id: str
    messages: list[Message]
    model: str | None
    response_format: ResponseFormat
    capabilities_required: frozenset[Capability]
    max_tokens: int | None
    temperature: float | None
    top_p: float | None
    timeout_ms: int
    stream: bool
    tools: list[Tool] | None
    tool_choice: ToolChoice | None
    metadata: dict
```

### Fields

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `trace_id` | `str` | Yes | generated | UUIDv7 or ULID, unique within process |
| `messages` | `list[Message]` | Yes | — | Non-empty |
| `model` | `str \| None` | No | `None` | User preference; not resolved |
| `response_format` | `ResponseFormat` | Yes | `text` | `text`, `json_object`, `json_schema`, `tool_calls` |
| `capabilities_required` | `frozenset[Capability]` | Yes | `frozenset()` | Capabilities the provider must support |
| `max_tokens` | `int \| None` | No | `None` | > 0 if set |
| `temperature` | `float \| None` | No | `0.7` | 0.0 to 2.0 if set |
| `top_p` | `float \| None` | No | `None` | 0.0 to 1.0 if set |
| `timeout_ms` | `int` | Yes | 30000 | > 0 |
| `stream` | `bool` | Yes | `False` | |
| `tools` | `list[Tool] \| None` | No | `None` | If set, `CAPABILITY_TOOLS` required |
| `tool_choice` | `ToolChoice` | No | `auto` | `none`, `auto`, `required`, or named tool |
| `metadata` | `dict` | No | `{}` | Extension passthrough |

### Invariants

- `trace_id` is non-empty and unique within process lifetime.
- `messages` is non-empty.
- The last message is from `user` or `tool`.
- `temperature` is `None` or in `[0.0, 2.0]`.
- `top_p` is `None` or in `[0.0, 1.0]`.
- `max_tokens` is `None` or `> 0`.
- If `tools` is non-empty, `CAPABILITY_TOOLS` is in `capabilities_required`.
- If `response_format == json_schema`, a `json_schema` is present.

### Serialization

```json
{
  "trace_id": "018f...",
  "messages": [...],
  "model": "llama-3.3-70b",
  "response_format": {"type": "text"},
  "capabilities_required": ["streaming"],
  "max_tokens": 1024,
  "temperature": 0.7,
  "timeout_ms": 30000,
  "stream": false,
  "metadata": {}
}
```

### Equality

- Two `Request` objects are equal iff all fields are equal.
- `trace_id` equality is sufficient for identity but not for value equality.

### Lifecycle

1. Created by caller or `RequestBuilder`.
2. Validated by Core.
3. Passed to Planner (read-only).
4. Passed to Runtime (read-only).
5. Logged by Extensions (copy may be redacted).
6. Archived with `Response`.

---

## 1.5 `Response`

```python
@frozen
class Response:
    trace_id: str
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: FinishReason
    provider: str
    model: str
    usage: Usage
    latency_ms: float
    metadata: dict
```

### Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `trace_id` | `str` | Yes | Matches `Request.trace_id` |
| `content` | `str \| None` | Yes | May be `None` if tool_calls or content filter |
| `tool_calls` | `list[ToolCall]` | Yes | Empty if none |
| `finish_reason` | `FinishReason` | Yes | Terminal reason |
| `provider` | `str` | Yes | Name of provider that executed |
| `model` | `str` | Yes | Actual model used |
| `usage` | `Usage` | Yes | Token counts (may be zeros if unavailable) |
| `latency_ms` | `float` | Yes | Wall time from execution start to finish |
| `metadata` | `dict` | Yes | Routing metadata, raw provider info, etc. |

### Invariants

- `trace_id` matches the originating `Request.trace_id`.
- `finish_reason` is from closed enum.
- If `finish_reason == "tool_calls"`, `tool_calls` is non-empty.
- `provider` and `model` are non-empty.
- `latency_ms` is ≥ 0.
- `usage.total_tokens` ≥ `usage.prompt_tokens` + `usage.completion_tokens`.

### Serialization

```json
{
  "trace_id": "018f...",
  "content": "Hello! How can I help?",
  "tool_calls": [],
  "finish_reason": "completed",
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
  "latency_ms": 245.0,
  "metadata": {"candidates_tried": 1}
}
```

### Equality

- Two `Response` objects are equal iff all fields are equal (excluding `latency_ms` floating point, compare within ε).

### Lifecycle

1. Created by Runtime after successful execution.
2. Passed through Extensions (cache, metrics, logging).
3. Returned to caller.

---

## 1.6 `FinishReason` (Enum)

```python
class FinishReason(str, Enum):
    COMPLETED = "completed"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    ERROR = "error"
```

- Closed set.
- `ERROR` is used only when a request terminates due to Runtime failure, not for a valid model response.

---

## 1.7 `Usage`

```python
@frozen
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int | None
```

### Invariants

- All fields ≥ 0.
- If `total_tokens` is set, `total_tokens >= prompt_tokens + completion_tokens`.

### Serialization

```json
{"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}
```

### Default

```json
{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": null}
```

---

## 1.8 `Capability` (Enum)

```python
class Capability(str, Enum):
    STREAMING = "streaming"
    TOOLS = "tools"
    VISION = "vision"
    JSON_MODE = "json_mode"
    JSON_SCHEMA = "json_schema"
    FUNCTION_CALLING = "function_calling"
    LONG_CONTEXT = "long_context"
    REASONING = "reasoning"
```

- Closed set.
- New capabilities require Core update and Planner update.

---

## 1.9 `ResponseFormat`

```python
@frozen
class ResponseFormat:
    type: ResponseFormatType
    json_schema: dict | None = None
```

```python
class ResponseFormatType(str, Enum):
    TEXT = "text"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"
    TOOL_CALLS = "tool_calls"
```

### Invariants

- If `type == JSON_SCHEMA`, `json_schema` is non-`None` and valid JSON Schema.

---

## 1.10 `Tool` and `ToolCall`

```python
@frozen
class Tool:
    type: str  # "function"
    function: FunctionTool

@frozen
class FunctionTool:
    name: str
    description: str
    parameters: dict  # JSON Schema

@frozen
class ToolCall:
    id: str
    type: str  # "function"
    function: FunctionCall

@frozen
class FunctionCall:
    name: str
    arguments: str  # JSON string
```

### Invariants

- `Tool.function.parameters` is valid JSON Schema.
- `ToolCall.function.arguments` is valid JSON string.
- `ToolCall.id` is unique within a `Response`.

---

## 2. Planner Types

### 2.1 `ProviderMetadata`

```python
@frozen
class ProviderMetadata:
    name: str
    display_name: str
    adapter_type: str
    base_url: str
    api_key_env: str
    models: list[ModelMetadata]
    default_model: str
    priority: int
    capabilities: frozenset[Capability]
    privacy_level: PrivacyLevel
```

### Fields

| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | Stable identifier, e.g. `"groq"` |
| `display_name` | `str` | Human-readable name |
| `adapter_type` | `str` | Factory key, e.g. `"openai_compatible"` |
| `base_url` | `str` | Provider endpoint |
| `api_key_env` | `str` | Environment variable name for key |
| `models` | `list[ModelMetadata]` | All known models |
| `default_model` | `str` | Fallback model |
| `priority` | `int` | Lower = tried earlier when scores tie |
| `capabilities` | `frozenset[Capability]` | Provider-wide capabilities |
| `privacy_level` | `PrivacyLevel` | `no_training`, `may_train`, `unknown` |

### Invariants

- `name` is unique in registry.
- `default_model` exists in `models`.
- `models` is non-empty.

---

### 2.2 `ModelMetadata`

```python
@frozen
class ModelMetadata:
    id: str
    display_name: str
    max_context_tokens: int
    max_output_tokens: int | None
    capabilities: frozenset[Capability]
    cost_per_1k_input: float  # 0.0 for free
    cost_per_1k_output: float
    quality_score: float  # 0.0–1.0
    latency_score: float  # 0.0–1.0
```

### Invariants

- `max_context_tokens` > 0.
- `max_output_tokens` is `None` or > 0.
- `quality_score` and `latency_score` in `[0.0, 1.0]`.

---

### 2.3 `Candidate`

```python
@frozen
class Candidate:
    provider: str
    model: str
    score: float
    estimated_tokens: int
    estimated_latency_ms: float
    reason: str  # human-readable selection reason
```

### Invariants

- `provider` and `model` reference a valid `ProviderMetadata` and `ModelMetadata`.
- `score` is a real number, higher is better.
- `estimated_tokens` ≥ 0.
- `estimated_latency_ms` ≥ 0.

---

### 2.4 `ExecutionPlan`

```python
@frozen
class ExecutionPlan:
    trace_id: str
    request: Request
    candidates: list[Candidate]
    fallback_policy: FallbackPolicy
    timeout_policy: TimeoutPolicy
    retry_policy: RetryPolicy
    required_capabilities: frozenset[Capability]
```

### Invariants

- `candidates` is non-empty iff the request is satisfiable.
- `candidates` is sorted by `score` descending.
- No duplicate `(provider, model)` pairs.
- `trace_id` matches `request.trace_id`.

### Equality

- Two plans are equal if their `candidates`, policies, and `request` are equal.

---

### 2.5 Policies

```python
@frozen
class FallbackPolicy:
    max_providers: int  # max number of providers to try
    provider_order: str  # "score", "priority", "round_robin"

@frozen
class TimeoutPolicy:
    total_ms: int
    connect_ms: int
    first_token_ms: int | None  # for streaming

@frozen
class RetryPolicy:
    max_retries: int
    backoff_base_ms: int
    backoff_max_ms: int
    retryable_errors: set[str]  # error categories
```

---

## 3. Runtime Types

### 3.1 `Adapter` (Abstract Interface)

```python
class Adapter(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def is_configured(self) -> bool: ...

    def execute(self, plan: ExecutionPlan, candidate: Candidate) -> Response: ...

    def stream(self, plan: ExecutionPlan, candidate: Candidate) -> Iterator[str | Response]: ...

    def health_check(self) -> HealthStatus: ...
```

### Invariants

- `execute` and `stream` never leak credentials.
- `stream` yields content chunks; final yield is a complete `Response`.
- `health_check` is safe to call without consuming quota.

---

### 3.2 `AdapterConfig`

```python
@frozen
class AdapterConfig:
    provider_name: str
    base_url: str
    api_key: Secret  # redacted in repr
    extra_headers: dict
    extra_body: dict
```

### Invariants

- `api_key` is wrapped in `Secret` type and redacted in `__repr__` and `__str__`.
- `base_url` is valid URL.

---

### 3.3 `ExecutionResult`

```python
@frozen
class ExecutionResult:
    response: Response | None
    error: ExecutionError | None
    attempts: list[Attempt]
    final_state: TerminalState
```

### Invariants

- Exactly one of `response` or `error` is non-None.
- `final_state` is one of `COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT`.
- `attempts` has at least one entry.

---

### 3.4 `Attempt`

```python
@frozen
class Attempt:
    trace_id: str
    provider: str
    model: str
    started_at: datetime
    ended_at: datetime | None
    error: ExecutionError | None
    usage_before: UsageSnapshot
    usage_after: UsageSnapshot | None
```

---

### 3.5 `ExecutionError`

```python
@frozen
class ExecutionError:
    trace_id: str
    provider: str | None
    category: ErrorCategory
    message: str  # safe, no secrets
    recoverable: bool
    retryable: bool
    cause: Exception | None  # not serialized
```

```python
class ErrorCategory(str, Enum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    VALIDATION = "validation"
    CONTENT_FILTER = "content_filter"
    CONTEXT_LENGTH = "context_length"
    UNKNOWN = "unknown"
```

---

## 4. Extension Types

### 4.1 `Extension` (Abstract Interface)

```python
class Extension(Protocol):
    def on_request(self, request: Request) -> Request: ...
    def on_plan(self, plan: ExecutionPlan) -> None: ...
    def on_execution_start(self, plan: ExecutionPlan) -> None: ...
    def on_execution_end(self, result: ExecutionResult) -> None: ...
    def on_response(self, response: Response) -> Response: ...
```

### Invariants

- `on_request` and `on_response` may return a copy but must preserve Core invariants.
- Extensions must not mutate input objects in place.
- Extensions may raise `ExtensionError`; such errors are caught and logged unless configured fatal.

---

### 4.2 `UsageStore` (Abstract Interface)

```python
class UsageStore(Protocol):
    def get(self, provider: str, model: str, day: date) -> UsageRecord: ...
    def increment(self, provider: str, model: str, day: date, prompt_tokens: int, completion_tokens: int) -> None: ...
    def reset_day(self, day: date) -> None: ...
```

---

### 4.3 `Cache` (Abstract Interface)

```python
class Cache(Protocol):
    def get(self, key: str) -> Response | None: ...
    def set(self, key: str, response: Response, ttl: int | None = None) -> None: ...
```

Cache key must be derived from deterministic `Request` fields (messages, model, temperature, response_format, etc.).

---

## 5. Serialization Rules

### 5.1 JSON

- All Core and Planner types must round-trip through JSON without data loss.
- `Secret` values are serialized as `"***"`.
- `Exception` objects are not serialized; only their safe message.
- Datetime fields use ISO 8601 UTC strings.

### 5.2 String Representation

- `__repr__` and `__str__` of Core/Planner types must not include secrets.
- Long `content` fields may be truncated to 200 characters in `__repr__`.
- `Secret.__repr__` returns `"Secret(***)"`.

### 5.3 Equality

- Equality is structural (all fields equal).
- `float` comparisons use approximate equality (ε = 1e-9).
- `Secret` equality compares the underlying string value, not the wrapper.

---

## 6. Lifecycle Diagrams

### 6.1 `Request` Lifecycle

```
Created → Validated → Planned → Executed → Archived
            ↓           ↓          ↓
        Invalid    NoProvider  Failed
```

### 6.2 `ExecutionPlan` Lifecycle

```
Created by Planner → Frozen → Passed to Runtime → Archived with Response
```

- Plans are immutable. Re-planning creates a new plan.

### 6.3 `Response` Lifecycle

```
Created by Runtime → Processed by Extensions → Returned to Caller → Archived
```

---

## 7. Error Taxonomy

| Error Class | Layer | Recoverable | Retryable | Notes |
|-------------|-------|-------------|-----------|-------|
| `ValidationError` | Core | No | No | Bad input |
| `PlanningError` | Planner | No | No | No candidate |
| `ExecutionError` | Runtime | Sometimes | Sometimes | Wraps provider errors |
| `ExtensionError` | Extensions | Usually | No | Middleware/plugin failure |
| `LLMError` | Any | Sometimes | Sometimes | Base class |

---

## 8. Public API Surface

### 8.1 `LLMClient`

```python
class LLMClient:
    def __init__(self, config: ClientConfig | None = None): ...

    def chat(self, prompt: str, **kwargs) -> Response: ...
    def stream(self, prompt: str, **kwargs) -> Iterator[str]: ...
    def achat(self, prompt: str, **kwargs) -> Awaitable[Response]: ...
    def astream(self, prompt: str, **kwargs) -> AsyncIterator[str]: ...

    def available_providers(self) -> list[str]: ...
    def usage(self) -> dict[str, UsageSummary]: ...

    # Advanced: expose full Request/Response pipeline
    def execute(self, request: Request) -> Response: ...
```

### 8.2 `ClientConfig`

```python
@frozen
class ClientConfig:
    registry_path: str | None
    usage_store: UsageStore | None
    extensions: list[Extension] | None
    default_timeout_ms: int = 30000
    log_level: str = "INFO"
```

---

## 9. Versioning Policy

- **Core types** are versioned separately from the kernel.
- A field may be **added** without a major version bump.
- A field may be **removed or renamed** only in a major version bump.
- `response_format` and `Capability` enum additions are minor version bumps.
