"""Tests for logging extension and secret redaction.

Covers DVM: E-01 (logging), E-02 (secret redaction), S-02 (Secret type redacts).
"""

import logging
from io import StringIO

import pytest

from llm_kernel.core import (
    FinishReason,
    Message,
    Request,
    Response,
    Role,
    Secret,
    Usage,
)
from llm_kernel.extensions.logging import (
    LoggingExtension,
    redact_request,
    redact_response,
    redact_secrets,
)


class TestSecretRedaction:
    @pytest.mark.parametrize(
        "key",
        [
            "gsk_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV",
            "AIzaSyFAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQR",
            "csk-fakeplaceholder1234567890abcdefghijklmnopqrstuv",
            "sk-or-v1-FAKEPLACEHOLDER1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234",
            "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz",
            "nvapi-FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV",
            "cfut_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV",
            "a9f5e5f4-1a09-492f-a818-e6c523f6fa1d",
        ],
    )
    def test_redact_known_key_formats(self, key):
        text = f"Error: invalid key {key}"
        redacted = redact_secrets(text)
        assert key not in redacted
        assert "***" in redacted

    def test_redact_preserves_non_key_text(self):
        text = "Hello, world! This is a normal message."
        assert redact_secrets(text) == text

    def test_redact_multiple_keys_in_one_string(self):
        text = (
            "keys: gsk_abc123def456ghi789jkl012mno345"
            " and AIzaSyFAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQR"
        )
        result = redact_secrets(text)
        assert "gsk_" not in result
        assert "AIza" not in result

    def test_secret_repr_redacts(self):
        secret = Secret("gsk_super_secret_key_123456789")
        assert "gsk_super_secret_key_123456789" not in repr(secret)
        assert "gsk_super_secret_key_123456789" not in str(secret)

    def test_secret_str_redacts(self):
        secret = Secret("my-api-key-12345")
        assert "my-api-key-12345" not in str(secret)


class TestRequestRedaction:
    def test_redact_request_truncates_long_content(self):
        long_content = "A" * 500
        req = Request(messages=[Message(role=Role.USER, content=long_content)])
        safe = redact_request(req)
        assert len(safe["messages"][0]["content"]) <= 203  # 200 + "..."
        assert safe["messages"][0]["content"].endswith("...")

    def test_redact_request_preserves_short_content(self):
        req = Request(messages=[Message(role=Role.USER, content="Hello!")])
        safe = redact_request(req)
        assert safe["messages"][0]["content"] == "Hello!"

    def test_redact_request_includes_trace_id(self):
        req = Request(messages=[Message(role=Role.USER, content="Hi")])
        safe = redact_request(req)
        assert safe["trace_id"] == req.trace_id

    def test_redact_request_no_secrets(self):
        req = Request(
            messages=[
                Message(
                    role=Role.USER,
                    content="My key is gsk_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV",
                )
            ]
        )
        safe = redact_request(req)
        safe_str = str(safe)
        assert "gsk_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV" not in safe_str


class TestResponseRedaction:
    @pytest.fixture
    def response(self):
        return Response(
            trace_id="t1",
            content="Hello!",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            latency_ms=123.4,
        )

    def test_redact_response_includes_provider(self, response):
        safe = redact_response(response)
        assert safe["provider"] == "groq"

    def test_redact_response_truncates_long_content(self):
        response = Response(
            trace_id="t1",
            content="B" * 500,
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            latency_ms=123.4,
        )
        safe = redact_response(response)
        assert len(safe["content"]) <= 203
        assert safe["content"].endswith("...")


class TestLoggingExtension:
    @pytest.fixture
    def log_capture(self):
        """Capture log output into a string buffer."""
        logger = logging.getLogger("test_llm_kernel")
        logger.setLevel(logging.DEBUG)
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        return logger, stream

    def test_logging_extension_implements_protocol(self):
        from llm_kernel.extensions import Extension

        ext = LoggingExtension()
        assert isinstance(ext, Extension)

    def test_on_request_logs_trace_id(self, log_capture):
        logger, stream = log_capture
        ext = LoggingExtension(logger=logger, level=logging.INFO)
        req = Request(messages=[Message(role=Role.USER, content="Hello!")])
        ext.on_request(req)
        output = stream.getvalue()
        assert req.trace_id in output

    def test_on_request_redacts_secrets_in_log(self, log_capture):
        logger, stream = log_capture
        ext = LoggingExtension(logger=logger, level=logging.INFO)
        req = Request(
            messages=[
                Message(
                    role=Role.USER,
                    content="My key is gsk_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV",
                )
            ]
        )
        ext.on_request(req)
        output = stream.getvalue()
        assert "gsk_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV" not in output

    def test_on_response_logs_provider(self, log_capture):
        logger, stream = log_capture
        ext = LoggingExtension(logger=logger, level=logging.INFO)
        resp = Response(
            trace_id="t1",
            content="Hello!",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            latency_ms=123.4,
        )
        ext.on_response(resp)
        output = stream.getvalue()
        assert "groq" in output
        assert "t1" in output

    def test_on_request_returns_request_unchanged(self):
        ext = LoggingExtension()
        req = Request(messages=[Message(role=Role.USER, content="Hello!")])
        result = ext.on_request(req)
        assert result is req

    def test_on_response_returns_response_unchanged(self):
        ext = LoggingExtension()
        resp = Response(
            trace_id="t1",
            content="Hello!",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            latency_ms=123.4,
        )
        result = ext.on_response(resp)
        assert result is resp
