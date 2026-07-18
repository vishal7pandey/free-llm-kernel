"""Tests for llm_kernel.core — specification-driven, TDD style.

These tests are derived from INTERFACE.md and ARCHITECTURE.md.
Run: uv run pytest tests/unit/core -v
"""

import json
from dataclasses import FrozenInstanceError

import pytest


class TestRole:
    def test_role_enum_values(self):
        from llm_kernel.core import Role

        assert Role.SYSTEM == "system"
        assert Role.USER == "user"
        assert Role.ASSISTANT == "assistant"
        assert Role.TOOL == "tool"

    def test_role_closed_set(self):
        from llm_kernel.core import Role

        with pytest.raises(ValueError):
            Role("invalid")


class TestCapability:
    def test_capability_closed_set(self):
        from llm_kernel.core import Capability

        assert Capability.STREAMING == "streaming"
        assert Capability.TOOLS == "tools"
        with pytest.raises(ValueError):
            Capability("new_cap")


class TestFinishReason:
    def test_finish_reason_closed_set(self):
        from llm_kernel.core import FinishReason

        assert FinishReason.COMPLETED == "completed"
        assert FinishReason.LENGTH == "length"
        with pytest.raises(ValueError):
            FinishReason("other")


class TestMessage:
    def test_message_text(self):
        from llm_kernel.core import Message, Role

        m = Message(role=Role.USER, content="Hello!")
        assert m.role == Role.USER
        assert m.content == "Hello!"

    def test_message_requires_content(self):
        from llm_kernel.core import Message, Role, ValidationError

        with pytest.raises(ValidationError):
            Message(role=Role.USER, content="")

    def test_message_user_cannot_be_empty(self):
        from llm_kernel.core import Message, Role, ValidationError

        with pytest.raises(ValidationError):
            Message(role=Role.USER, content="  ")

    def test_message_is_frozen(self):
        from llm_kernel.core import Message, Role, ValidationError

        m = Message(role=Role.USER, content="Hello!")
        with pytest.raises(ValidationError):
            m.content = "Changed"


class TestResponseFormat:
    def test_response_format_text(self):
        from llm_kernel.core import ResponseFormat, ResponseFormatType

        rf = ResponseFormat(type=ResponseFormatType.TEXT)
        assert rf.type == ResponseFormatType.TEXT
        assert rf.json_schema is None

    def test_response_format_json_schema_requires_schema(self):
        from llm_kernel.core import ResponseFormat, ResponseFormatType, ValidationError

        with pytest.raises(ValidationError):
            ResponseFormat(type=ResponseFormatType.JSON_SCHEMA)

    def test_response_format_json_schema_validates(self):
        from llm_kernel.core import ResponseFormat, ResponseFormatType

        rf = ResponseFormat(
            type=ResponseFormatType.JSON_SCHEMA,
            json_schema={"type": "object"},
        )
        assert rf.json_schema == {"type": "object"}


class TestUsage:
    def test_usage_positive_tokens(self):
        from llm_kernel.core import Usage

        u = Usage(prompt_tokens=10, completion_tokens=8, total_tokens=18)
        assert u.prompt_tokens == 10
        assert u.completion_tokens == 8
        assert u.total_tokens == 18

    def test_usage_negative_rejected(self):
        from llm_kernel.core import Usage, ValidationError

        with pytest.raises(ValidationError):
            Usage(prompt_tokens=-1, completion_tokens=0, total_tokens=None)

    def test_usage_total_constraint(self):
        from llm_kernel.core import Usage, ValidationError

        with pytest.raises(ValidationError):
            Usage(prompt_tokens=10, completion_tokens=8, total_tokens=15)


class TestRequest:
    def test_request_basic(self):
        from llm_kernel.core import Request, Message, Role

        r = Request(messages=[Message(role=Role.USER, content="Hello!")])
        assert len(r.messages) == 1
        assert r.messages[0].content == "Hello!"
        assert r.trace_id is not None
        assert r.stream is False

    def test_request_requires_messages(self):
        from llm_kernel.core import Request, ValidationError

        with pytest.raises(ValidationError):
            Request(messages=[])

    def test_request_temperature_range(self):
        from llm_kernel.core import Request, Message, Role, ValidationError

        base = {"messages": [Message(role=Role.USER, content="Hi")]}
        Request(**base, temperature=0.0)
        Request(**base, temperature=2.0)
        with pytest.raises(ValidationError):
            Request(**base, temperature=-0.1)
        with pytest.raises(ValidationError):
            Request(**base, temperature=2.1)

    def test_request_top_p_range(self):
        from llm_kernel.core import Request, Message, Role, ValidationError

        base = {"messages": [Message(role=Role.USER, content="Hi")]}
        Request(**base, top_p=0.5)
        with pytest.raises(ValidationError):
            Request(**base, top_p=1.5)

    def test_request_max_tokens_positive(self):
        from llm_kernel.core import Request, Message, Role, ValidationError

        base = {"messages": [Message(role=Role.USER, content="Hi")]}
        with pytest.raises(ValidationError):
            Request(**base, max_tokens=0)
        with pytest.raises(ValidationError):
            Request(**base, max_tokens=-5)

    def test_request_timeout_positive(self):
        from llm_kernel.core import Request, Message, Role, ValidationError

        base = {"messages": [Message(role=Role.USER, content="Hi")]}
        with pytest.raises(ValidationError):
            Request(**base, timeout_ms=0)

    def test_request_last_message_must_be_user_or_tool(self):
        from llm_kernel.core import Request, Message, Role, ValidationError

        with pytest.raises(ValidationError):
            Request(
                messages=[
                    Message(role=Role.USER, content="Hi"),
                    Message(role=Role.ASSISTANT, content="Hello"),
                ]
            )

    def test_request_trace_id_unique(self):
        from llm_kernel.core import Request, Message, Role

        r1 = Request(messages=[Message(role=Role.USER, content="A")])
        r2 = Request(messages=[Message(role=Role.USER, content="B")])
        assert r1.trace_id != r2.trace_id

    def test_request_tools_require_capability(self):
        from llm_kernel.core import Request, Message, Role, Tool, FunctionTool, ValidationError

        tool = Tool(
            type="function",
            function=FunctionTool(name="fn", description="desc", parameters={}),
        )
        with pytest.raises(ValidationError):
            Request(
                messages=[Message(role=Role.USER, content="Hi")],
                tools=[tool],
            )

    def test_request_frozen(self):
        from llm_kernel.core import Request, Message, Role, ValidationError

        r = Request(messages=[Message(role=Role.USER, content="Hi")])
        with pytest.raises(ValidationError):
            r.temperature = 0.5


class TestResponse:
    def test_response_basic(self):
        from llm_kernel.core import Response, FinishReason, Usage

        resp = Response(
            trace_id="t1",
            content="Hello!",
            tool_calls=[],
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b-versatile",
            usage=Usage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
            latency_ms=100.0,
        )
        assert resp.content == "Hello!"
        assert resp.provider == "groq"

    def test_response_content_filter_with_none(self):
        from llm_kernel.core import Response, FinishReason, Usage

        resp = Response(
            trace_id="t1",
            content=None,
            tool_calls=[],
            finish_reason=FinishReason.CONTENT_FILTER,
            provider="google",
            model="gemini-2.0-flash",
            usage=Usage(prompt_tokens=10, completion_tokens=0, total_tokens=10),
            latency_ms=50.0,
        )
        assert resp.content is None

    def test_response_finish_reason_tool_calls_requires_tool_calls(self):
        from llm_kernel.core import Response, FinishReason, Usage, ValidationError

        with pytest.raises(ValidationError):
            Response(
                trace_id="t1",
                content=None,
                tool_calls=[],
                finish_reason=FinishReason.TOOL_CALLS,
                provider="groq",
                model="x",
                usage=Usage(prompt_tokens=10, completion_tokens=0, total_tokens=10),
                latency_ms=1.0,
            )

    def test_response_latency_non_negative(self):
        from llm_kernel.core import Response, FinishReason, Usage, ValidationError

        with pytest.raises(ValidationError):
            Response(
                trace_id="t1",
                content="x",
                tool_calls=[],
                finish_reason=FinishReason.COMPLETED,
                provider="p",
                model="m",
                usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                latency_ms=-1.0,
            )

    def test_response_frozen(self):
        from llm_kernel.core import Response, FinishReason, Usage, ValidationError

        resp = Response(
            trace_id="t1",
            content="x",
            tool_calls=[],
            finish_reason=FinishReason.COMPLETED,
            provider="p",
            model="m",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=1.0,
        )
        with pytest.raises(ValidationError):
            resp.provider = "other"


class TestSerialization:
    def test_request_json_roundtrip(self):
        from llm_kernel.core import Request, Message, Role

        r = Request(
            messages=[Message(role=Role.USER, content="Hello!")],
            temperature=0.7,
        )
        data = r.to_json()
        loaded = Request.from_json(data)
        assert loaded == r

    def test_response_json_roundtrip(self):
        from llm_kernel.core import Response, FinishReason, Usage

        resp = Response(
            trace_id="t1",
            content="Hello!",
            tool_calls=[],
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b-versatile",
            usage=Usage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
            latency_ms=100.0,
        )
        data = resp.to_json()
        loaded = Response.from_json(data)
        assert loaded == resp

    def test_secret_redacted_in_json(self):
        from llm_kernel.core import Secret

        s = Secret("sk-test")
        data = json.dumps({"key": s.to_json()})
        assert "sk-test" not in data


class TestSecret:
    def test_secret_repr_redacted(self):
        from llm_kernel.core import Secret

        s = Secret("super-secret-key")
        assert "super-secret-key" not in repr(s)
        assert "super-secret-key" not in str(s)
        assert "***" in repr(s)

    def test_secret_equality(self):
        from llm_kernel.core import Secret

        assert Secret("a") == Secret("a")
        assert Secret("a") != Secret("b")
