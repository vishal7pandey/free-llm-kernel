"""Core types, contracts, errors, and validation for the Free LLM Kernel.

The Core layer is pure: no I/O, no network, no mutable state, no logging.
"""

from __future__ import annotations

import json
import re
import uuid
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import core_schema as cs

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class KernelError(Exception):
    """Base error for the Free LLM Kernel."""

    def __init__(self, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.__cause__ = cause


class ValidationError(KernelError):
    """Raised when a Core object fails validation."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Capability(StrEnum):
    STREAMING = "streaming"
    TOOLS = "tools"
    VISION = "vision"
    JSON_MODE = "json_mode"
    JSON_SCHEMA = "json_schema"
    FUNCTION_CALLING = "function_calling"
    LONG_CONTEXT = "long_context"
    REASONING = "reasoning"


CAPABILITY_ALIASES: dict[str, Capability] = {
    "streaming": Capability.STREAMING,
    "stream": Capability.STREAMING,
    "tools": Capability.TOOLS,
    "tool": Capability.TOOLS,
    "tool_calling": Capability.TOOLS,
    "function_calling": Capability.FUNCTION_CALLING,
    "functions": Capability.FUNCTION_CALLING,
    "vision": Capability.VISION,
    "image": Capability.VISION,
    "multimodal": Capability.VISION,
    "json": Capability.JSON_MODE,
    "json_mode": Capability.JSON_MODE,
    "json_object": Capability.JSON_MODE,
    "json_schema": Capability.JSON_SCHEMA,
    "structured": Capability.JSON_SCHEMA,
    "long_context": Capability.LONG_CONTEXT,
    "long": Capability.LONG_CONTEXT,
    "large_context": Capability.LONG_CONTEXT,
    "reasoning": Capability.REASONING,
    "think": Capability.REASONING,
    "thinking": Capability.REASONING,
}


def resolve_capabilities(
    capabilities: str | Capability | list[str | Capability] | None,
) -> frozenset[Capability]:
    """Resolve user-friendly capability strings into a frozenset of Capability.

    Accepts single strings, Capability enums, or lists of either.
    Friendly aliases like "json", "vision", "tools" are supported.

    Examples::

        resolve_capabilities("vision")                    # {Capability.VISION}
        resolve_capabilities(["json", "tools"])           # {Capability.JSON_MODE, Capability.TOOLS}
        resolve_capabilities(Capability.STREAMING)        # {Capability.STREAMING}
        resolve_capabilities(None)                        # frozenset()
    """
    if capabilities is None:
        return frozenset()
    if isinstance(capabilities, Capability):
        return frozenset({capabilities})
    caps = [capabilities] if isinstance(capabilities, str) else list(capabilities)

    resolved: set[Capability] = set()
    for cap in caps:
        if isinstance(cap, Capability):
            resolved.add(cap)
        elif isinstance(cap, str):
            key = cap.lower().strip()
            mapped = CAPABILITY_ALIASES.get(key)
            if mapped is None:
                try:
                    mapped = Capability(key)
                except ValueError as exc:
                    valid = sorted(CAPABILITY_ALIASES.keys())
                    raise ValidationError(
                        f"Unknown capability '{cap}'. Valid options: {valid}"
                    ) from exc
            resolved.add(mapped)
    return frozenset(resolved)


class FinishReason(StrEnum):
    COMPLETED = "completed"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    ERROR = "error"


class ResponseFormatType(StrEnum):
    TEXT = "text"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"
    TOOL_CALLS = "tool_calls"


class ErrorCategory(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    VALIDATION = "validation"
    CONTENT_FILTER = "content_filter"
    CONTEXT_LENGTH = "context_length"
    UNKNOWN = "unknown"


class PrivacyLevel(StrEnum):
    NO_TRAINING = "no_training"
    MAY_TRAIN = "may_train"
    OPT_OUT_REQUIRED = "opt_out_required"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Utility Types
# ---------------------------------------------------------------------------


class Secret:
    """Wrapper that redacts the underlying value in str/repr and JSON."""

    def __init__(self, value: str):
        if not isinstance(value, str):
            raise ValidationError("Secret value must be a string")
        self._value = value

    def get(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        if isinstance(other, str):
            return self._value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    def to_json(self) -> str:
        return "***"

    @classmethod
    def from_json(cls, value: Any) -> Self:
        if value == "***":
            raise ValidationError("Cannot deserialize a redacted Secret")
        return cls(value)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> cs.CoreSchema:
        return cs.no_info_plain_validator_function(
            cls._pydantic_validate,
            serialization=cs.plain_serializer_function_ser_schema(
                lambda v, info: (
                    v._value if info and getattr(info, "mode", None) == "python" else "***"
                ),
                return_schema=cs.str_schema(),
                when_used="json-unless-none",
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> dict[str, Any]:
        return {"type": "string"}

    @classmethod
    def _pydantic_validate(cls, value: Any) -> Secret:
        if isinstance(value, Secret):
            return value
        if isinstance(value, str):
            return cls(value)
        raise ValidationError(f"Secret must be a string, got {type(value).__name__}")


# ---------------------------------------------------------------------------
# Core Data Models
# ---------------------------------------------------------------------------


class KernelModel(BaseModel):
    """Base model for all Core types: frozen, JSON serializable, validated."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        use_enum_values=True,
        validate_assignment=True,
    )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str | bytes | dict[str, Any]) -> Self:
        if isinstance(data, (str, bytes)):
            return cls.model_validate_json(data)
        return cls.model_validate(data)

    def __repr__(self) -> str:
        # Default repr, but Secret fields are redacted by their own __repr__.
        return super().__repr__()

    def __setattr__(self, name: str, value: Any) -> None:
        """Convert Pydantic frozen-instance errors into our public ValidationError."""
        try:
            super().__setattr__(name, value)
        except PydanticValidationError as exc:
            raise ValidationError(
                f"Cannot mutate {self.__class__.__name__}: {name} is frozen"
            ) from exc


class ContentPart(KernelModel):
    type: Literal["text", "image_url", "audio_url", "image_base64", "audio_base64"]

    # Common fallback for unknown field layout; subclasses define their own.
    model_config = ConfigDict(frozen=True, extra="allow")


class TextPart(ContentPart):
    type: Literal["text"] = "text"
    text: str


class ImageUrlPart(ContentPart):
    type: Literal["image_url"] = "image_url"
    image_url: dict[str, str]


class AudioUrlPart(ContentPart):
    type: Literal["audio_url"] = "audio_url"
    audio_url: dict[str, str]


class ImageBase64Part(ContentPart):
    type: Literal["image_base64"] = "image_base64"
    data: str
    mime_type: str = "image/png"


class AudioBase64Part(ContentPart):
    type: Literal["audio_base64"] = "audio_base64"
    data: str
    mime_type: str = "audio/wav"


ContentPartUnion = TextPart | ImageUrlPart | AudioUrlPart | ImageBase64Part | AudioBase64Part


class Message(KernelModel):
    role: Role
    content: str | list[ContentPartUnion]
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_message(self) -> Self:
        if self.role == Role.USER:
            content = self.content
            if isinstance(content, str) and content.strip() == "":
                raise ValidationError("User message content cannot be empty")
            elif isinstance(content, list) and not content:
                raise ValidationError("User message content list cannot be empty")
        return self


class ResponseFormat(KernelModel):
    type: ResponseFormatType = ResponseFormatType.TEXT
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_json_schema(self) -> Self:
        if self.type == ResponseFormatType.JSON_SCHEMA and not self.json_schema:
            raise ValidationError("json_schema is required when response_format is JSON_SCHEMA")
        return self


class Tool(KernelModel):
    type: Literal["function"] = "function"
    function: FunctionTool


class FunctionTool(KernelModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolCall(KernelModel):
    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class FunctionCall(KernelModel):
    name: str
    arguments: str

    @model_validator(mode="after")
    def _validate_json(self) -> Self:
        try:
            json.loads(self.arguments)
        except json.JSONDecodeError as exc:
            raise ValidationError("Tool function arguments must be valid JSON") from exc
        return self


class Usage(KernelModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int | None = None

    @model_validator(mode="after")
    def _validate_usage(self) -> Self:
        if self.prompt_tokens < 0 or self.completion_tokens < 0:
            raise ValidationError("Token counts must be non-negative")
        if self.total_tokens is not None:
            minimum = self.prompt_tokens + self.completion_tokens
            if self.total_tokens < minimum:
                raise ValidationError(
                    f"total_tokens ({self.total_tokens}) must be >= "
                    f"prompt_tokens + completion_tokens ({minimum})"
                )
        return self


# ---------------------------------------------------------------------------
# Trace ID generation
# ---------------------------------------------------------------------------


def generate_trace_id() -> str:
    """Generate a trace ID that is unique within process lifetime.

    Uses UUIDv7-ish timestamp + random, encoded as base58-like compact string.
    For simplicity we use standard UUID4; uniqueness within a process is guaranteed
    by the random generator. Switch to ULID/UUIDv7 for sortability if needed.
    """
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Request and Response
# ---------------------------------------------------------------------------


class Request(KernelModel):
    trace_id: str = Field(default_factory=generate_trace_id)
    messages: list[Message]
    model: str | None = None
    response_format: ResponseFormat = Field(default_factory=ResponseFormat)
    capabilities_required: frozenset[Capability] = Field(default_factory=frozenset)
    max_tokens: int | None = None
    temperature: float | None = 0.7
    top_p: float | None = None
    timeout_ms: int = 30_000
    stream: bool = False
    tools: list[Tool] | None = None
    tool_choice: str | None = "auto"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_request(self) -> Self:
        if not self.messages:
            raise ValidationError("Request must contain at least one message")

        last = self.messages[-1]
        if last.role not in (Role.USER, Role.TOOL):
            raise ValidationError("Last message must be from user or tool")

        if self.temperature is not None and not (0.0 <= self.temperature <= 2.0):
            raise ValidationError("temperature must be between 0.0 and 2.0")

        if self.top_p is not None and not (0.0 <= self.top_p <= 1.0):
            raise ValidationError("top_p must be between 0.0 and 1.0")

        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValidationError("max_tokens must be positive")

        if self.timeout_ms <= 0:
            raise ValidationError("timeout_ms must be positive")

        if self.tools and Capability.TOOLS not in self.capabilities_required:
            raise ValidationError(
                "capabilities_required must include Capability.TOOLS when tools are provided"
            )

        return self


class Response(KernelModel):
    trace_id: str
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason
    provider: str
    model: str
    usage: Usage
    latency_ms: float
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_response(self) -> Self:
        if self.latency_ms < 0:
            raise ValidationError("latency_ms must be non-negative")

        if self.finish_reason == FinishReason.TOOL_CALLS and not self.tool_calls:
            raise ValidationError("finish_reason TOOL_CALLS requires non-empty tool_calls")

        return self


# ---------------------------------------------------------------------------
# Runtime Types
# ---------------------------------------------------------------------------


class ExecutionError(KernelError):
    """Raised by Runtime when a provider execution fails."""

    def __init__(
        self,
        *,
        trace_id: str,
        provider: str | None,
        category: ErrorCategory,
        message: str,
        recoverable: bool = False,
        retryable: bool = False,
        cause: Exception | None = None,
    ):
        safe_message = self._redact(message)
        super().__init__(safe_message, cause=cause)
        self.trace_id = trace_id
        self.provider = provider
        self.category = category
        self._message = safe_message
        self.recoverable = recoverable
        self.retryable = retryable

    def __str__(self) -> str:
        return self._message

    @staticmethod
    def _redact(text: str) -> str:
        """Remove common secret patterns from error strings."""
        # API keys and tokens
        patterns = [
            r"sk-[a-zA-Z0-9_-]{20,}",
            r"AIza[0-9A-Za-z_-]{35,}",
            r"nvapi-[a-zA-Z0-9_-]{20,}",
            r"[a-f0-9]{32,}",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "***", text)
        return text


# ---------------------------------------------------------------------------
# Extension Types
# ---------------------------------------------------------------------------


class UsageRecord(KernelModel):
    provider: str
    model: str
    day: str  # ISO date string
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


from llm_kernel.core.state_machine import (  # noqa: E402
    TERMINAL_STATES,
    InvalidStateTransition,
    RequestState,
    RequestStateMachine,
)

# ---------------------------------------------------------------------------
# Legacy public API compatibility
# ---------------------------------------------------------------------------

__all__ = [
    "KernelError",
    "ValidationError",
    "ExecutionError",
    "InvalidStateTransition",
    "RequestState",
    "RequestStateMachine",
    "TERMINAL_STATES",
    "Role",
    "Capability",
    "CAPABILITY_ALIASES",
    "resolve_capabilities",
    "FinishReason",
    "ResponseFormatType",
    "ErrorCategory",
    "PrivacyLevel",
    "Secret",
    "KernelModel",
    "ContentPart",
    "TextPart",
    "ImageUrlPart",
    "AudioUrlPart",
    "ImageBase64Part",
    "AudioBase64Part",
    "Message",
    "ResponseFormat",
    "Tool",
    "FunctionTool",
    "ToolCall",
    "FunctionCall",
    "Usage",
    "Request",
    "Response",
    "generate_trace_id",
    "UsageRecord",
]
