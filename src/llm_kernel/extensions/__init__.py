"""Extensions layer: usage tracking, logging, cache, sessions, security, plugins.

The Extensions layer sits at the top of the stack and may import from all
lower layers (runtime, planner, core).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from llm_kernel.core import (
    KernelError,
    Request,
    Response,
    Usage,
    UsageRecord,
)
from llm_kernel.planner import ExecutionPlan

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ExtensionError(KernelError):
    """Raised when an extension fails in a way that should be visible."""


# ---------------------------------------------------------------------------
# Extension Protocol (ARCHITECTURE.md §8.4, INTERFACE.md §4.1)
# ---------------------------------------------------------------------------


@runtime_checkable
class Extension(Protocol):
    """Middleware hook contract.

    Extensions observe and wrap the request lifecycle. They may return
    copies of Request/Response but must never mutate inputs in place.
    """

    def on_request(self, request: Request) -> Request: ...
    def on_plan(self, plan: ExecutionPlan) -> None: ...
    def on_execution_start(self, plan: ExecutionPlan) -> None: ...
    def on_execution_end(self, result: Any) -> None: ...
    def on_response(self, response: Response) -> Response: ...


# ---------------------------------------------------------------------------
# Middleware Chain
# ---------------------------------------------------------------------------


class MiddlewareChain:
    """Ordered extension executor.

    Default order: request logging → security scrubbing → cache →
    planner/runtime → response processing → cache write → metrics →
    response logging.

    Extensions that raise are caught; errors are swallowed unless the
    extension is registered as fatal.
    """

    def __init__(self, extensions: list[Extension] | None = None):
        self._extensions: list[Extension] = list(extensions) if extensions else []
        self._fatal: set[int] = set()

    def add(self, extension: Extension, *, fatal: bool = False) -> None:
        """Register an extension. Fatal extensions' errors propagate."""
        self._extensions.append(extension)
        if fatal:
            self._fatal.add(id(extension))

    def remove(self, extension: Extension) -> None:
        """Remove a registered extension."""
        self._extensions = [e for e in self._extensions if e is not extension]
        self._fatal.discard(id(extension))

    @property
    def extensions(self) -> list[Extension]:
        return list(self._extensions)

    def on_request(self, request: Request) -> Request:
        current = request
        for ext in self._extensions:
            try:
                current = ext.on_request(current)
            except Exception:
                if id(ext) in self._fatal:
                    raise
        return current

    def on_plan(self, plan: ExecutionPlan) -> None:
        for ext in self._extensions:
            try:
                ext.on_plan(plan)
            except Exception:
                if id(ext) in self._fatal:
                    raise

    def on_execution_start(self, plan: ExecutionPlan) -> None:
        for ext in self._extensions:
            try:
                ext.on_execution_start(plan)
            except Exception:
                if id(ext) in self._fatal:
                    raise

    def on_execution_end(self, result: Any) -> None:
        for ext in self._extensions:
            try:
                ext.on_execution_end(result)
            except Exception:
                if id(ext) in self._fatal:
                    raise

    def on_response(self, response: Response) -> Response:
        current = response
        for ext in self._extensions:
            try:
                current = ext.on_response(current)
            except Exception:
                if id(ext) in self._fatal:
                    raise
        return current


# ---------------------------------------------------------------------------
# Usage Store
# ---------------------------------------------------------------------------


class UsageStore:
    """Persistent per-day, per-provider usage tracker.

    Stores a JSON file mapping ``{date: {provider:model: UsageRecord}}``.
    Thread-safe via an internal lock.
    """

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else None
        self._data: dict[str, dict[str, UsageRecord]] = {}
        self._lock = threading.Lock()
        self._load()

    def record(
        self,
        provider: str,
        model: str,
        usage: Usage,
    ) -> None:
        """Record a successful request's token usage."""
        with self._lock:
            day = self._today()
            key = f"{provider}:{model}"

            day_data = self._data.setdefault(day, {})
            existing = day_data.get(key)

            if existing is not None:
                day_data[key] = UsageRecord(
                    provider=provider,
                    model=model,
                    day=day,
                    request_count=existing.request_count + 1,
                    prompt_tokens=existing.prompt_tokens + usage.prompt_tokens,
                    completion_tokens=existing.completion_tokens + usage.completion_tokens,
                )
            else:
                day_data[key] = UsageRecord(
                    provider=provider,
                    model=model,
                    day=day,
                    request_count=1,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )

            self._save()

    def get_today(self) -> list[UsageRecord]:
        """Return all usage records for today."""
        day = self._today()
        return list(self._data.get(day, {}).values())

    def get_provider_usage_today(self, provider: str) -> UsageRecord | None:
        """Return the aggregate usage record for a provider today, or None."""
        records = self.get_today()
        for record in records:
            if record.provider == provider:
                return record
        return None

    def get_day(self, day: str) -> list[UsageRecord]:
        """Return all usage records for a specific day."""
        return list(self._data.get(day, {}).values())

    def clear_expired(self, keep_days: int = 30) -> None:
        """Remove entries older than keep_days."""
        cutoff = (datetime.now(UTC) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        self._data = {d: v for d, v in self._data.items() if d >= cutoff}
        self._save()

    def to_world_state_usage(self) -> dict[str, UsageRecord]:
        """Return a dict suitable for WorldState.usage (keyed by provider name)."""
        result: dict[str, UsageRecord] = {}
        for record in self.get_today():
            if record.provider not in result:
                result[record.provider] = record
            else:
                existing = result[record.provider]
                result[record.provider] = UsageRecord(
                    provider=record.provider,
                    model=record.model,
                    day=record.day,
                    request_count=existing.request_count + record.request_count,
                    prompt_tokens=existing.prompt_tokens + record.prompt_tokens,
                    completion_tokens=existing.completion_tokens + record.completion_tokens,
                )
        return result

    def _today(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for day, entries in raw.items():
                self._data[day] = {
                    key: UsageRecord.model_validate(entry) for key, entry in entries.items()
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    def _save(self) -> None:
        if self._path is None:
            return
        serializable: dict[str, dict[str, Any]] = {}
        for day, entries in self._data.items():
            serializable[day] = {key: record.model_dump() for key, record in entries.items()}
        self._path.write_text(json.dumps(serializable, indent=2))


__all__ = ["Extension", "ExtensionError", "MiddlewareChain", "UsageStore"]
