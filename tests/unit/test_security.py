"""Tests for credential non-leakage in errors and logs.

Covers DVM:
- R-03: Credentials never leave Runtime layer in errors or logs
- S-02: Secret type redacts in __repr__ and __str__
- E-05: API keys redacted in error messages
"""

import pytest
import respx
from httpx import Response as HttpxResponse

from llm_kernel.core import (
    ErrorCategory,
    ExecutionError,
    Message,
    Request,
    Role,
    Secret,
)
from llm_kernel.extensions.logging import redact_secrets
from llm_kernel.runtime import (
    AdapterConfig,
    OpenAICompatibleAdapter,
)


class TestSecretType:
    def test_secret_repr_does_not_leak(self):
        secret = Secret("gsk_my_super_secret_key_123456789")
        assert "gsk_my_super_secret_key_123456789" not in repr(secret)

    def test_secret_str_does_not_leak(self):
        secret = Secret("AIzaSyFAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQR")
        assert "AIzaSyFAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQR" not in str(secret)

    def test_secret_get_returns_value(self):
        secret = Secret("my-key")
        assert secret.get() == "my-key"

    def test_secret_equality_compares_values(self):
        assert Secret("key1") == Secret("key1")
        assert Secret("key1") != Secret("key2")


class TestErrorCredentialLeakage:
    def test_execution_error_does_not_contain_key(self):
        api_key = "gsk_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV"
        err = ExecutionError(
            trace_id="t1",
            provider="groq",
            category=ErrorCategory.AUTH,
            message=(
                "Authentication failed for key:"
                " gsk_FAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQRSTUV"
            ),
            recoverable=False,
            retryable=False,
        )
        # The error message itself might contain the key if constructed badly,
        # but redact_secrets should scrub it
        safe = redact_secrets(str(err))
        assert api_key not in safe

    def test_execution_error_safe_message(self):
        err = ExecutionError(
            trace_id="t1",
            provider="groq",
            category=ErrorCategory.AUTH,
            message="Invalid API key",
            recoverable=False,
            retryable=False,
        )
        assert "Invalid API key" in str(err)
        # No actual key should be present
        assert "gsk_" not in str(err)
        assert "AIza" not in str(err)

    @respx.mock
    def test_adapter_401_error_does_not_leak_key(self):
        api_key = "gsk_test_key_abcdef123456789"
        config = AdapterConfig(
            provider_name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=Secret(api_key),
        )
        adapter = OpenAICompatibleAdapter(config=config)

        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=HttpxResponse(401, json={"error": {"message": "Invalid API key"}})
        )

        req = Request(messages=[Message(role=Role.USER, content="hi")])
        from llm_kernel.planner import Candidate, ExecutionPlan

        plan = ExecutionPlan(
            trace_id=req.trace_id,
            request=req,
            candidates=[Candidate(provider="groq", model="llama-3.3-70b", score=1.0)],
        )

        with pytest.raises(Exception) as exc_info:
            adapter.execute(plan, "llama-3.3-70b")

        error_str = str(exc_info.value)
        assert api_key not in error_str

    @respx.mock
    def test_adapter_500_error_does_not_leak_key(self):
        api_key = "AIzaSyFAKEPLACEHOLDER1234567890ABCDEFGHIJKLMNOPQR"
        config = AdapterConfig(
            provider_name="google",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key=Secret(api_key),
        )
        adapter = OpenAICompatibleAdapter(config=config)

        respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
            return_value=HttpxResponse(500, json={"error": {"message": "Internal server error"}})
        )

        req = Request(messages=[Message(role=Role.USER, content="hi")])
        from llm_kernel.planner import Candidate, ExecutionPlan

        plan = ExecutionPlan(
            trace_id=req.trace_id,
            request=req,
            candidates=[Candidate(provider="google", model="gemini-2.0-flash", score=1.0)],
        )

        with pytest.raises(Exception) as exc_info:
            adapter.execute(plan, "gemini-2.0-flash")

        error_str = str(exc_info.value)
        assert api_key not in error_str

    def test_adapter_config_repr_does_not_leak_key(self):
        api_key = "gsk_super_secret_123456789"
        config = AdapterConfig(
            provider_name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=Secret(api_key),
        )
        config_repr = repr(config)
        assert api_key not in config_repr
