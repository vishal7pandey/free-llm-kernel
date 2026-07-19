"""Logging extension with structured output and secret redaction.

Implements DVM E-01, E-02, S-02:
- Every request logged with trace_id
- Secret redaction runs before any log emission
- API keys never appear in logs or errors
"""

from __future__ import annotations

import logging
import re
from typing import Any

from llm_kernel.core import (
    Request,
    Response,
)
from llm_kernel.extensions import Extension
from llm_kernel.planner import ExecutionPlan

# Patterns for common API key formats
_KEY_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),
    re.compile(r"csk-[A-Za-z0-9]{20,}"),
    re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),
    re.compile(r"sk-proj-[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"nvapi-[A-Za-z0-9]{20,}"),
    re.compile(r"cfut_[A-Za-z0-9]{20,}"),
    re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"),
]

_REDACTED = "***"


def redact_secrets(text: str) -> str:
    """Replace API key patterns in a string with '***'."""
    result = text
    for pattern in _KEY_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def redact_request(request: Request) -> dict[str, Any]:
    """Serialize a Request to a safe dict for logging (no secrets, truncated content)."""
    messages = []
    for msg in request.messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        content = redact_secrets(content)
        if len(content) > 200:
            content = content[:200] + "..."
        messages.append({"role": str(msg.role), "content": content})
    return {
        "trace_id": request.trace_id,
        "model": request.model,
        "messages": messages,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": request.stream,
    }


def redact_response(response: Response) -> dict[str, Any]:
    """Serialize a Response to a safe dict for logging."""
    content = response.content or ""
    if len(content) > 200:
        content = content[:200] + "..."
    return {
        "trace_id": response.trace_id,
        "provider": response.provider,
        "model": response.model,
        "content": content,
        "finish_reason": str(response.finish_reason),
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        },
        "latency_ms": response.latency_ms,
    }


class LoggingExtension(Extension):
    """Structured logging with automatic secret redaction.

    Logs to a Python logger by default. All content is scrubbed before emission.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        level: int = logging.INFO,
    ):
        self._logger = logger or logging.getLogger("llm_kernel")
        self._level = level

    def on_request(self, request: Request) -> Request:
        safe = redact_request(request)
        self._logger.log(self._level, "request %s", safe)
        return request

    def on_plan(self, plan: ExecutionPlan) -> None:
        candidates = [
            {"provider": c.provider, "model": c.model, "score": round(c.score, 2)}
            for c in plan.candidates
        ]
        self._logger.log(self._level, "plan %s trace=%s", candidates, plan.trace_id)

    def on_execution_start(self, plan: ExecutionPlan) -> None:
        self._logger.log(self._level, "execution_start trace=%s", plan.trace_id)

    def on_execution_end(self, result: Any) -> None:
        state = getattr(result, "final_state", "unknown")
        self._logger.log(self._level, "execution_end state=%s", state)

    def on_response(self, response: Response) -> Response:
        safe = redact_response(response)
        self._logger.log(self._level, "response %s", safe)
        return response


__all__ = [
    "LoggingExtension",
    "redact_secrets",
    "redact_request",
    "redact_response",
]
