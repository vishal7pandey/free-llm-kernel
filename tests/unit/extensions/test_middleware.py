"""Tests for the Extension protocol and middleware chain.

Run: uv run pytest tests/unit/extensions/test_middleware.py -v
"""

import pytest
from datetime import datetime, timezone

from llm_kernel.core import (
    Capability,
    ExecutionError,
    FinishReason,
    Message,
    Request,
    Response,
    Role,
    Usage,
    ErrorCategory,
)
from llm_kernel.planner import Candidate, ExecutionPlan, RetryPolicy
from llm_kernel.runtime import ExecutionResult, Attempt
from llm_kernel.extensions import Extension, MiddlewareChain, ExtensionError


class RecordingExtension(Extension):
    """Records every hook call in order."""
    def __init__(self, name: str = "recorder"):
        self.name = name
        self.calls: list[str] = []

    def on_request(self, request: Request) -> Request:
        self.calls.append(f"{self.name}:on_request")
        return request

    def on_plan(self, plan: ExecutionPlan) -> None:
        self.calls.append(f"{self.name}:on_plan")

    def on_execution_start(self, plan: ExecutionPlan) -> None:
        self.calls.append(f"{self.name}:on_execution_start")

    def on_execution_end(self, result: ExecutionResult) -> None:
        self.calls.append(f"{self.name}:on_execution_end")

    def on_response(self, response: Response) -> Response:
        self.calls.append(f"{self.name}:on_response")
        return response


class TestExtensionProtocol:
    def test_extension_is_protocol(self):
        """Extension should be a Protocol that any class can implement."""
        ext = RecordingExtension()
        assert isinstance(ext, Extension)

    def test_on_request_returns_request(self):
        ext = RecordingExtension()
        req = Request(messages=[Message(role=Role.USER, content="hi")])
        result = ext.on_request(req)
        assert result is req

    def test_on_response_returns_response(self):
        ext = RecordingExtension()
        resp = Response(
            trace_id="t1",
            content="hello",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=100.0,
        )
        result = ext.on_response(resp)
        assert result is resp


class TestMiddlewareChain:
    @pytest.fixture
    def sample_request(self):
        return Request(messages=[Message(role=Role.USER, content="hi")])

    @pytest.fixture
    def sample_plan(self, sample_request):
        return ExecutionPlan(
            trace_id=sample_request.trace_id,
            request=sample_request,
            candidates=[Candidate(provider="groq", model="llama-3.3-70b", score=1.0)],
        )

    @pytest.fixture
    def sample_response(self):
        return Response(
            trace_id="t1",
            content="hello",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=100.0,
        )

    @pytest.fixture
    def sample_result(self, sample_response):
        return ExecutionResult(
            response=sample_response,
            final_state="completed",
            attempts=[],
        )

    def test_empty_chain_passes_through(self, sample_request, sample_plan, sample_response, sample_result):
        chain = MiddlewareChain()
        assert chain.on_request(sample_request) is sample_request
        chain.on_plan(sample_plan)  # should not raise
        chain.on_execution_start(sample_plan)
        chain.on_execution_end(sample_result)
        assert chain.on_response(sample_response) is sample_response

    def test_single_extension_called(self, sample_request):
        ext = RecordingExtension("a")
        chain = MiddlewareChain([ext])
        chain.on_request(sample_request)
        assert ext.calls == ["a:on_request"]

    def test_multiple_extensions_called_in_order(self, sample_request, sample_plan, sample_response, sample_result):
        a = RecordingExtension("a")
        b = RecordingExtension("b")
        chain = MiddlewareChain([a, b])

        chain.on_request(sample_request)
        chain.on_plan(sample_plan)
        chain.on_execution_start(sample_plan)
        chain.on_execution_end(sample_result)
        chain.on_response(sample_response)

        assert a.calls == [
            "a:on_request", "a:on_plan", "a:on_execution_start",
            "a:on_execution_end", "a:on_response",
        ]
        assert b.calls == [
            "b:on_request", "b:on_plan", "b:on_execution_start",
            "b:on_execution_end", "b:on_response",
        ]

    def test_on_request_chain_composes(self, sample_request):
        """Each extension sees the output of the previous one."""
        class TaggingExtension(Extension):
            def __init__(self):
                self.seen_metadata = []
            def on_request(self, request: Request) -> Request:
                self.seen_metadata = list(request.metadata.get("tags", []))
                return request.model_copy(update={"metadata": {**request.metadata, "tags": [*self.seen_metadata, "tag"]}})
            def on_plan(self, plan): pass
            def on_execution_start(self, plan): pass
            def on_execution_end(self, result): pass
            def on_response(self, response): return response

        ext1 = TaggingExtension()
        ext2 = TaggingExtension()
        chain = MiddlewareChain([ext1, ext2])

        result = chain.on_request(sample_request)
        assert ext1.seen_metadata == []
        assert ext2.seen_metadata == ["tag"]
        assert result.metadata["tags"] == ["tag", "tag"]

    def test_extension_error_is_caught(self, sample_request):
        class BadExtension(Extension):
            def on_request(self, request: Request) -> Request:
                raise ValueError("boom")
            def on_plan(self, plan): pass
            def on_execution_start(self, plan): pass
            def on_execution_end(self, result): pass
            def on_response(self, response): return response

        chain = MiddlewareChain([BadExtension()])
        # Should not raise — errors are caught and logged
        result = chain.on_request(sample_request)
        assert result is sample_request

    def test_add_extension(self, sample_request):
        ext = RecordingExtension("a")
        chain = MiddlewareChain()
        chain.add(ext)
        chain.on_request(sample_request)
        assert ext.calls == ["a:on_request"]

    def test_remove_extension(self, sample_request):
        ext = RecordingExtension("a")
        chain = MiddlewareChain([ext])
        chain.remove(ext)
        chain.on_request(sample_request)
        assert ext.calls == []
