"""Runtime layer: provider adapters, HTTP execution, retries, circuit breakers.

This layer is the only one allowed to make network calls.
"""

from __future__ import annotations

import contextlib
import json
import random
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx

from llm_kernel.core import (
    ErrorCategory,
    ExecutionError,
    FinishReason,
    FunctionCall,
    Message,
    Request,
    Response,
    Secret,
    ToolCall,
    Usage,
    ValidationError,
)
from llm_kernel.planner import (
    Candidate,
    ExecutionPlan,
    HealthSnapshot,
    ProviderMetadata,
    QuotaSnapshot,
)

# ---------------------------------------------------------------------------
# Configuration & Result Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterConfig:
    """Configuration for constructing a provider adapter."""

    provider_name: str
    base_url: str
    api_key: Secret
    extra_headers: dict[str, str] | None = None
    extra_body: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValidationError("base_url is required")


@dataclass(frozen=True)
class Attempt:
    """Record of a single provider execution attempt."""

    trace_id: str
    provider: str
    model: str
    started_at: str
    ended_at: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Health Tracker
# ---------------------------------------------------------------------------


class HealthTracker:
    """Mutable runtime health state for providers.

    Tracks per-provider health status, rolling latency averages, and
    daily request counts. Updated by the Executor after each attempt.
    The Planner can query this to make routing decisions.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

    def __init__(self, daily_limits: dict[str, int | None] | None = None):
        self._health: dict[str, str] = {}
        self._latency_samples: dict[str, list[float]] = {}
        self._request_counts: dict[str, int] = {}
        self._daily_limits = daily_limits or {}
        self._failure_streaks: dict[str, int] = {}

    def record_success(self, provider: str, latency_ms: float) -> None:
        samples = self._latency_samples.setdefault(provider, [])
        samples.append(latency_ms)
        if len(samples) > 20:
            samples.pop(0)

        self._failure_streaks[provider] = 0
        self._request_counts[provider] = self._request_counts.get(provider, 0) + 1

        if self._health.get(provider) == self.UNHEALTHY:
            self._health[provider] = self.DEGRADED
        elif self._health.get(provider) == self.DEGRADED:
            self._health[provider] = self.HEALTHY

    def record_failure(self, provider: str, category: str) -> None:
        streak = self._failure_streaks.get(provider, 0) + 1
        self._failure_streaks[provider] = streak

        if category == "rate_limit":
            self._health[provider] = self.DEGRADED
        elif streak >= 3:
            self._health[provider] = self.UNHEALTHY
        elif streak >= 2:
            self._health[provider] = self.DEGRADED

    def get_health(self) -> HealthSnapshot:
        return HealthSnapshot(dict(self._health))

    def get_quota(self) -> QuotaSnapshot:
        usage: dict[str, Any] = {}
        for provider, count in self._request_counts.items():
            usage[provider] = {
                "provider": provider,
                "model": "",
                "day": datetime.now(UTC).strftime("%Y-%m-%d"),
                "request_count": count,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
        latency: dict[str, float] = {}
        for provider, samples in self._latency_samples.items():
            if samples:
                latency[provider] = sum(samples) / len(samples)
        return QuotaSnapshot(usage=usage, latency=latency)

    def quota_remaining(self, provider: str) -> float:
        limit = self._daily_limits.get(provider)
        if limit is None or limit <= 0:
            return 1.0
        used = self._request_counts.get(provider, 0)
        return max(0.0, 1.0 - used / limit)

    def is_available(self, provider: str) -> bool:
        return self._health.get(provider, self.HEALTHY) != self.UNHEALTHY


@dataclass(frozen=True)
class ExecutionResult:
    """Final result of executing an ExecutionPlan."""

    response: Response | None = None
    error: ExecutionError | None = None
    attempts: list[Attempt] | None = field(default_factory=list)
    final_state: Literal["completed", "failed", "cancelled", "timed_out"] = "failed"

    def __post_init__(self) -> None:
        has_response = self.response is not None
        has_error = self.error is not None
        if has_response == has_error:
            raise ValidationError("ExecutionResult must have exactly one of response or error")


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Per-provider circuit breaker with CLOSED/OPEN/HALF_OPEN states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_ms: int = 30_000,
        half_open_max_calls: int = 1,
    ):
        if failure_threshold <= 0:
            raise ValidationError("failure_threshold must be positive")
        self.failure_threshold = failure_threshold
        self.cooldown_ms = cooldown_ms
        self.half_open_max_calls = half_open_max_calls
        self._state = self.CLOSED
        self._failure_count = 0
        self._opened_at: datetime | None = None
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        return self._state

    def allow_request(self) -> bool:
        """Return True if a request is currently allowed."""
        now = datetime.now(UTC)
        if self._state == self.CLOSED:
            return True
        if self._state == self.OPEN:
            if self._cooldown_elapsed(now):
                self._state = self.HALF_OPEN
                self._half_open_calls = 0
                return True
            return False
        if self._state == self.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        return False

    def record_failure(self) -> None:
        """Record a provider failure."""
        if self._state == self.HALF_OPEN:
            self._state = self.OPEN
            self._opened_at = datetime.now(UTC)
            return

        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = datetime.now(UTC)

    def record_success(self) -> None:
        """Record a provider success."""
        if self._state == self.HALF_OPEN:
            self._state = self.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_calls = 0
            return

        if self._state == self.OPEN:
            if self._cooldown_elapsed(datetime.now(UTC)):
                # Treat as a successful half-open probe.
                self._state = self.CLOSED
                self._failure_count = 0
                self._opened_at = None
                self._half_open_calls = 0
            return

        if self._state == self.CLOSED:
            self._failure_count = 0

    def _cooldown_elapsed(self, now: datetime) -> bool:
        if self._opened_at is None:
            return True
        elapsed_ms = (now - self._opened_at).total_seconds() * 1000
        return elapsed_ms > self.cooldown_ms


# ---------------------------------------------------------------------------
# Retry Engine
# ---------------------------------------------------------------------------


class RetryEngine:
    """Determines retryability and computes backoff delays."""

    DEFAULT_RETRYABLE = {"rate_limit", "timeout", "network", "server"}

    def __init__(
        self,
        max_retries: int = 2,
        base_ms: int = 500,
        max_ms: int = 16_000,
        retryable: set[str] | None = None,
        jitter: bool = True,
    ):
        if max_retries < 0:
            raise ValidationError("max_retries must be non-negative")
        if base_ms <= 0:
            raise ValidationError("base_ms must be positive")
        self.max_retries = max_retries
        self.base_ms = base_ms
        self.max_ms = max_ms
        self.retryable = retryable or set(self.DEFAULT_RETRYABLE)
        self.jitter = jitter

    def is_retryable(self, category: str) -> bool:
        return category in self.retryable

    def backoff_delay(self, attempt: int) -> int:
        """Exponential backoff with ±25% jitter, capped at max_ms."""
        delay = self.base_ms * (2**attempt)
        if self.jitter:
            delay = int(delay * random.uniform(0.75, 1.25))
        return int(min(delay, self.max_ms))


# ---------------------------------------------------------------------------
# Adapter Protocol and OpenAI-Compatible Adapter
# ---------------------------------------------------------------------------


class Adapter(Protocol):
    """Protocol for provider-specific execution adapters."""

    @property
    def provider_name(self) -> str: ...

    def execute(self, plan: ExecutionPlan, model: str) -> Response: ...

    def stream(self, plan: ExecutionPlan, model: str) -> Iterator[str]: ...

    def health_check(self) -> str: ...


class OpenAICompatibleAdapter:
    """Adapter for OpenAI-compatible HTTP endpoints."""

    def __init__(
        self,
        config: AdapterConfig,
        provider: ProviderMetadata | None = None,
        client: httpx.Client | None = None,
    ):
        self.config = config
        self.provider = provider
        self._client = client or httpx.Client(timeout=30.0)

    @property
    def provider_name(self) -> str:
        return self.config.provider_name

    def execute(self, plan: ExecutionPlan, model: str) -> Response:
        """Execute a non-streaming request and return a Response."""
        body = self._build_body(plan.request, model, stream=False)
        start = time.monotonic()
        http_response = self._post("chat/completions", body, plan.trace_id)
        latency_ms = (time.monotonic() - start) * 1000
        return self._parse_response(http_response, plan.trace_id, model, latency_ms)

    def stream(self, plan: ExecutionPlan, model: str) -> Iterator[str]:
        """Execute a streaming request and yield content chunks."""
        body = self._build_body(plan.request, model, stream=True)
        url = f"{self.config.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key.get()}",
            "Accept": "text/event-stream",
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        try:
            with self._client.stream(
                "POST",
                url,
                json=body,
                headers=headers,
                timeout=self._request_timeout(),
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    self._raise_http_error(response, plan.trace_id)
                yield from self._parse_stream(response)
        except httpx.TimeoutException as exc:
            raise ExecutionError(
                trace_id=plan.trace_id,
                provider=self.config.provider_name,
                category=ErrorCategory.TIMEOUT,
                message="Stream request timed out",
                recoverable=True,
                retryable=True,
                cause=exc,
            ) from exc
        except httpx.NetworkError as exc:
            raise ExecutionError(
                trace_id=plan.trace_id,
                provider=self.config.provider_name,
                category=ErrorCategory.NETWORK,
                message="Stream network error",
                recoverable=True,
                retryable=True,
                cause=exc,
            ) from exc

    def health_check(self) -> str:
        """Return 'healthy', 'degraded', or 'unhealthy'."""
        try:
            response = self._client.get(f"{self.config.base_url}/models")
            if response.status_code == 200:
                return "healthy"
            return "unhealthy"
        except httpx.HTTPError:
            return "unhealthy"

    def _post(
        self,
        path: str,
        body: dict[str, Any],
        trace_id: str,
    ) -> httpx.Response:
        url = f"{self.config.base_url}/{path}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key.get()}",
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        try:
            response = self._client.post(
                url,
                json=body,
                headers=headers,
                timeout=self._request_timeout(),
            )
            if response.status_code >= 400:
                self._raise_http_error(response, trace_id)
            return response
        except httpx.TimeoutException as exc:
            raise ExecutionError(
                trace_id=trace_id,
                provider=self.config.provider_name,
                category=ErrorCategory.TIMEOUT,
                message="Request timed out",
                recoverable=True,
                retryable=True,
                cause=exc,
            ) from exc
        except httpx.NetworkError as exc:
            raise ExecutionError(
                trace_id=trace_id,
                provider=self.config.provider_name,
                category=ErrorCategory.NETWORK,
                message="Network error",
                recoverable=True,
                retryable=True,
                cause=exc,
            ) from exc
        except httpx.HTTPError as exc:
            raise ExecutionError(
                trace_id=trace_id,
                provider=self.config.provider_name,
                category=ErrorCategory.UNKNOWN,
                message=f"HTTP error: {exc}",
                recoverable=False,
                retryable=False,
                cause=exc,
            ) from exc

    def _request_timeout(self) -> float:
        """Use a sane default timeout for HTTP requests."""
        return 30.0

    def _raise_http_error(self, response: httpx.Response, trace_id: str) -> None:
        provider = self.config.provider_name
        try:
            payload = response.json()
            message = str(payload)
        except json.JSONDecodeError:
            message = response.text or response.reason_phrase

        category = self._classify_status(response.status_code)
        retryable = category in {"rate_limit", "timeout", "network", "server"}
        recoverable = category not in {"auth", "validation"}

        raise ExecutionError(
            trace_id=trace_id,
            provider=provider,
            category=ErrorCategory(category),
            message=message,
            recoverable=recoverable,
            retryable=retryable,
        )

    @staticmethod
    def _classify_status(status_code: int) -> str:
        if status_code == 401 or status_code == 403:
            return "auth"
        if status_code == 429:
            return "rate_limit"
        if status_code == 408:
            return "timeout"
        if status_code == 413:
            return "context_length"
        if 500 <= status_code < 600:
            return "server"
        if 400 <= status_code < 500:
            return "validation"
        return "unknown"

    def _build_body(self, request: Request, model: str, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [self._message_to_dict(m) for m in request.messages],
            "stream": stream,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.response_format and request.response_format.type != "text":
            body["response_format"] = request.response_format.model_dump(exclude_none=True)
        if request.tools:
            body["tools"] = [t.model_dump(exclude_none=True) for t in request.tools]
        if request.tools and request.tool_choice:
            body["tool_choice"] = request.tool_choice
        if self.config.extra_body:
            body.update(self.config.extra_body)
        return body

    def _message_to_dict(self, message: Message) -> dict[str, Any]:
        role = str(message.role)
        if isinstance(message.content, str):
            content: Any = message.content
        else:
            content = [part.model_dump(exclude_none=True) for part in message.content]
        data = {"role": role, "content": content}
        if message.name:
            data["name"] = message.name
        return data

    def _parse_response(
        self, http_response: httpx.Response, trace_id: str, model: str, latency_ms: float = 0.0,
    ) -> Response:
        try:
            data = http_response.json()
        except json.JSONDecodeError as exc:
            raise ExecutionError(
                trace_id=trace_id,
                provider=self.config.provider_name,
                category=ErrorCategory.SERVER,
                message="Provider returned invalid JSON",
                recoverable=False,
                retryable=False,
                cause=exc,
            ) from exc

        choices = data.get("choices", [])
        if not choices:
            raise ExecutionError(
                trace_id=trace_id,
                provider=self.config.provider_name,
                category=ErrorCategory.SERVER,
                message="Provider returned no choices",
                recoverable=False,
                retryable=False,
            )

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content")
        if content is None:
            content = ""

        finish_reason_value = choice.get("finish_reason", "stop")
        if finish_reason_value == "stop":
            finish_reason_value = "completed"

        try:
            finish_reason = FinishReason(finish_reason_value)
        except ValueError:
            finish_reason = FinishReason.ERROR

        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens"),
        )

        # Parse tool calls from OpenAI-compatible format
        tool_calls: list[ToolCall] = []
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            for raw_tc in raw_tool_calls:
                tc_id = raw_tc.get("id", "")
                tc_type = raw_tc.get("type", "function")
                tc_function = raw_tc.get("function", {})
                tc_name = tc_function.get("name", "")
                tc_arguments = tc_function.get("arguments", "{}")
                with contextlib.suppress(ValidationError):
                    tool_calls.append(
                        ToolCall(
                            id=tc_id,
                            type=tc_type,
                            function=FunctionCall(name=tc_name, arguments=tc_arguments),
                        )
                    )

        # Adjust finish_reason for tool calls
        if tool_calls and finish_reason == FinishReason.COMPLETED:
            finish_reason = FinishReason.TOOL_CALLS
        elif not tool_calls and finish_reason == FinishReason.TOOL_CALLS:
            finish_reason = FinishReason.COMPLETED

        return Response(
            trace_id=trace_id,
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            provider=self.config.provider_name,
            model=data.get("model", model),
            usage=usage,
            latency_ms=latency_ms,
            metadata={"raw": data},
        )

    def _parse_stream(self, http_response: httpx.Response) -> Iterator[str]:
        try:
            for raw_line in http_response.iter_lines():
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                if not data_str:
                    continue

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = data.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
        except (httpx.HTTPError, json.JSONDecodeError):
            # Streaming parse errors are typically fatal; caller can decide to continue.
            return


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class Executor:
    """Executes an ExecutionPlan across candidates with retry and fallback."""

    def __init__(
        self,
        adapters: Mapping[str, Adapter],
        retry_engine: RetryEngine | None = None,
        circuit_breakers: dict[str, CircuitBreaker] | None = None,
        health_tracker: HealthTracker | None = None,
        sleep_fn: Any = time.sleep,
    ):
        self.adapters = adapters
        self.retry_engine = retry_engine or RetryEngine()
        self.circuit_breakers = circuit_breakers or {}
        self.health_tracker = health_tracker
        self._sleep = sleep_fn

    def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """Execute a plan and return a terminal ExecutionResult."""
        attempts: list[Attempt] = []
        last_error: ExecutionError | None = None

        for candidate in plan.candidates:
            cb = self._circuit_breaker(candidate.provider)
            if not cb.allow_request():
                continue

            adapter = self.adapters.get(candidate.provider)
            if adapter is None:
                last_error = ExecutionError(
                    trace_id=plan.trace_id,
                    provider=candidate.provider,
                    category=ErrorCategory.UNKNOWN,
                    message=f"No adapter configured for provider {candidate.provider}",
                    recoverable=False,
                    retryable=False,
                )
                continue

            try:
                return self._try_candidate(plan, candidate, adapter, cb, attempts)
            except ExecutionError as exc:
                last_error = exc
                continue

        return ExecutionResult(
            error=last_error,
            final_state="failed",
            attempts=attempts,
        )

    def _try_candidate(
        self,
        plan: ExecutionPlan,
        candidate: Candidate,
        adapter: Adapter,
        cb: CircuitBreaker,
        attempts: list[Attempt],
    ) -> ExecutionResult:
        max_retries = plan.retry_policy.max_retries
        for attempt in range(max_retries + 1):
            started = datetime.now(UTC).isoformat()
            try:
                response = adapter.execute(plan, candidate.model)
                cb.record_success()
                if self.health_tracker is not None:
                    self.health_tracker.record_success(
                        candidate.provider, response.latency_ms,
                    )
                attempts.append(
                    Attempt(
                        trace_id=plan.trace_id,
                        provider=candidate.provider,
                        model=candidate.model,
                        started_at=started,
                        ended_at=datetime.now(UTC).isoformat(),
                        error=None,
                    )
                )
                return ExecutionResult(
                    response=response,
                    final_state="completed",
                    attempts=attempts,
                )
            except ExecutionError as exc:
                attempts.append(
                    Attempt(
                        trace_id=plan.trace_id,
                        provider=candidate.provider,
                        model=candidate.model,
                        started_at=started,
                        ended_at=datetime.now(UTC).isoformat(),
                        error=str(exc),
                    )
                )

                should_retry = (
                    exc.retryable
                    and self.retry_engine.is_retryable(exc.category)
                    and attempt < max_retries
                )
                if should_retry:
                    delay = self.retry_engine.backoff_delay(attempt)
                    self._sleep(delay / 1000.0)
                    continue

                cb.record_failure()
                if self.health_tracker is not None:
                    self.health_tracker.record_failure(
                        candidate.provider, exc.category.value,
                    )
                raise exc

        raise ExecutionError(
            trace_id=plan.trace_id,
            provider=candidate.provider,
            category=ErrorCategory.UNKNOWN,
            message=f"Exhausted retries for {candidate.provider}:{candidate.model}",
        )

    def _circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        return self.circuit_breakers.setdefault(provider_name, CircuitBreaker())


__all__ = [
    "AdapterConfig",
    "Attempt",
    "ExecutionResult",
    "CircuitBreaker",
    "HealthTracker",
    "RetryEngine",
    "Adapter",
    "OpenAICompatibleAdapter",
    "Executor",
]
