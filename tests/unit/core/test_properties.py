"""Property tests for Core types.

Covers DVM:
- C-02: Request.trace_id is unique within process lifetime
- C-07: All Core types round-trip through JSON without data loss
"""

from llm_kernel.core import (
    Capability,
    FinishReason,
    Message,
    Request,
    Response,
    Role,
    Usage,
    generate_trace_id,
)


class TestTraceIdUniqueness:
    def test_10000_unique_trace_ids(self):
        ids = {generate_trace_id() for _ in range(10_000)}
        assert len(ids) == 10_000

    def test_trace_id_non_empty(self):
        assert len(generate_trace_id()) > 0

    def test_request_generates_unique_trace_id(self):
        req1 = Request(messages=[Message(role=Role.USER, content="hi")])
        req2 = Request(messages=[Message(role=Role.USER, content="hi")])
        assert req1.trace_id != req2.trace_id


class TestJsonRoundTrip:
    def test_message_round_trip(self):
        msg = Message(role=Role.USER, content="Hello, world!")
        data = msg.model_dump()
        restored = Message.model_validate(data)
        assert restored == msg

    def test_message_with_metadata_round_trip(self):
        msg = Message(role=Role.SYSTEM, content="You are helpful", metadata={"key": "value"})
        data = msg.model_dump()
        restored = Message.model_validate(data)
        assert restored == msg

    def test_request_round_trip(self):
        req = Request(
            messages=[
                Message(role=Role.SYSTEM, content="Be helpful"),
                Message(role=Role.USER, content="What is 2+2?"),
            ],
            model="llama-3.3-70b",
            temperature=0.5,
            max_tokens=100,
        )
        data = req.model_dump()
        restored = Request.model_validate(data)
        assert restored == req

    def test_response_round_trip(self):
        resp = Response(
            trace_id="test-trace-123",
            content="The answer is 4.",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
            latency_ms=245.0,
        )
        data = resp.model_dump()
        restored = Response.model_validate(data)
        assert restored == resp

    def test_usage_round_trip(self):
        usage = Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        data = usage.model_dump()
        restored = Usage.model_validate(data)
        assert restored == usage

    def test_request_with_capabilities_round_trip(self):
        req = Request(
            messages=[Message(role=Role.USER, content="hi")],
            capabilities_required=frozenset({Capability.STREAMING, Capability.TOOLS}),
        )
        data = req.model_dump()
        restored = Request.model_validate(data)
        assert restored.capabilities_required == req.capabilities_required

    def test_request_json_string_round_trip(self):
        import json

        req = Request(
            messages=[Message(role=Role.USER, content="Hello!")],
            model="groq-model",
            temperature=0.7,
        )
        json_str = json.dumps(req.model_dump(mode="json"))
        restored = Request.model_validate(json.loads(json_str))
        assert restored == req
