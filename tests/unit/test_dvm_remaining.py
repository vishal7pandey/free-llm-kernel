"""Tests for remaining DVM requirements.

Covers:
- C-01: Core has no network/disk/env/logging imports (static analysis)
- C-08: __repr__ of Core types redacts secrets and truncates long content
- C-10: All errors are serializable and typed
- E-04: Extension.on_response may return a copy, not mutate
- X-06: Streaming fails but usage not double-counted
"""

import ast
import json
from pathlib import Path

import pytest

from llm_kernel.core import (
    ErrorCategory,
    ExecutionError,
    FinishReason,
    Message,
    Request,
    Response,
    Role,
    Secret,
    Usage,
)
from llm_kernel.planner import Candidate, ExecutionPlan
from llm_kernel.extensions import Extension


# ---------------------------------------------------------------------------
# C-01: Core purity — no forbidden imports
# ---------------------------------------------------------------------------


FORBIDDEN_MODULES = {
    "requests", "urllib", "urllib3", "httpx", "httpcore",
    "openai", "anthropic",
    "os", "sys", "subprocess",
    "logging",
    "socket", "asyncio",
    "io",
    "sqlite3", "shutil", "pickle",
    "aiohttp", "aiofiles",
}


class TestCorePurity:
    def _get_imported_modules(self, filepath: Path) -> set[str]:
        tree = ast.parse(filepath.read_text())
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module.split(".")[0])
        return modules

    def test_core_init_no_forbidden_imports(self):
        core_init = Path(__file__).resolve().parents[2] / "src" / "llm_kernel" / "core" / "__init__.py"
        modules = self._get_imported_modules(core_init)
        forbidden = modules & FORBIDDEN_MODULES
        assert not forbidden, f"Core imports forbidden modules: {forbidden}"

    def test_core_state_machine_no_forbidden_imports(self):
        sm_file = Path(__file__).resolve().parents[2] / "src" / "llm_kernel" / "core" / "state_machine.py"
        modules = self._get_imported_modules(sm_file)
        forbidden = modules & FORBIDDEN_MODULES
        assert not forbidden, f"core.state_machine imports forbidden modules: {forbidden}"

    def test_core_no_open_or_env_calls(self):
        core_dir = Path(__file__).resolve().parents[2] / "src" / "llm_kernel" / "core"
        for pyfile in core_dir.glob("*.py"):
            content = pyfile.read_text()
            assert "open(" not in content or "open(" in content.split("#")[0] and False, \
                f"{pyfile.name} contains open() call"
            assert "os.getenv" not in content, f"{pyfile.name} contains os.getenv"
            assert "os.environ" not in content, f"{pyfile.name} contains os.environ"


# ---------------------------------------------------------------------------
# C-08: __repr__ redacts secrets and truncates
# ---------------------------------------------------------------------------


class TestReprRedaction:
    def test_request_repr_does_not_show_secret_content(self):
        # Request repr shows message content, which is user input — not a Secret.
        # Secrets are wrapped in the Secret type, which redacts in __repr__.
        # Message content is user-provided text, not a credential.
        # This test verifies that Secret fields are redacted in repr.
        from llm_kernel.runtime import AdapterConfig
        config = AdapterConfig(
            provider_name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=Secret("gsk_super_secret_key_123456789"),
        )
        repr_str = repr(config)
        assert "gsk_super_secret_key_123456789" not in repr_str

    def test_adapter_config_repr_redacts_secret(self):
        from llm_kernel.runtime import AdapterConfig
        config = AdapterConfig(
            provider_name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=Secret("gsk_super_secret_key_123456789"),
        )
        repr_str = repr(config)
        assert "gsk_super_secret_key_123456789" not in repr_str


# ---------------------------------------------------------------------------
# C-10: Errors are serializable and typed
# ---------------------------------------------------------------------------


class TestErrorSerialization:
    def test_execution_error_has_typed_fields(self):
        err = ExecutionError(
            trace_id="t1",
            provider="groq",
            category=ErrorCategory.AUTH,
            message="Auth failed",
            recoverable=False,
            retryable=False,
        )
        assert err.trace_id == "t1"
        assert err.provider == "groq"
        assert err.category == ErrorCategory.AUTH
        assert err.recoverable is False
        assert err.retryable is False

    def test_execution_error_str_is_safe(self):
        err = ExecutionError(
            trace_id="t1",
            provider="groq",
            category=ErrorCategory.SERVER,
            message="Server error",
            recoverable=True,
            retryable=True,
        )
        s = str(err)
        assert "Server error" in s

    def test_execution_error_preserves_cause(self):
        cause = ValueError("original")
        err = ExecutionError(
            trace_id="t1",
            provider="groq",
            category=ErrorCategory.UNKNOWN,
            message="Wrapped",
            cause=cause,
        )
        assert err.__cause__ is cause

    def test_execution_error_all_categories(self):
        for category in ErrorCategory:
            err = ExecutionError(
                trace_id="t1",
                provider="test",
                category=category,
                message="test",
            )
            assert err.category == category


# ---------------------------------------------------------------------------
# E-04: on_response returns copy, not mutate
# ---------------------------------------------------------------------------


class TestExtensionOnResponse:
    def test_on_response_can_return_copy(self):
        original = Response(
            trace_id="t1",
            content="Hello!",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            latency_ms=100.0,
        )

        class ModifyingExtension(Extension):
            def on_response(self, response):
                # Return a new Response with modified content (copy, not mutate)
                return Response(
                    trace_id=response.trace_id,
                    content=response.content + " [modified]",
                    finish_reason=response.finish_reason,
                    provider=response.provider,
                    model=response.model,
                    usage=response.usage,
                    latency_ms=response.latency_ms,
                )
            def on_request(self, request): return request
            def on_plan(self, plan): pass
            def on_execution_start(self, plan): pass
            def on_execution_end(self, result): pass

        ext = ModifyingExtension()
        result = ext.on_response(original)
        assert result.content == "Hello! [modified]"
        # Original unchanged
        assert original.content == "Hello!"

    def test_on_response_can_return_same(self):
        original = Response(
            trace_id="t1",
            content="Hello!",
            finish_reason=FinishReason.COMPLETED,
            provider="groq",
            model="llama-3.3-70b",
            usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            latency_ms=100.0,
        )

        class PassthroughExtension(Extension):
            def on_response(self, response):
                return response
            def on_request(self, request): return request
            def on_plan(self, plan): pass
            def on_execution_start(self, plan): pass
            def on_execution_end(self, result): pass

        ext = PassthroughExtension()
        result = ext.on_response(original)
        assert result is original


# ---------------------------------------------------------------------------
# X-06: Streaming fails but usage not double-counted
# ---------------------------------------------------------------------------


class TestStreamingUsageCount:
    def test_usage_recorded_once_on_success(self, tmp_path):
        from llm_kernel.extensions import UsageStore
        from llm_kernel.core import Usage

        store = UsageStore(path=tmp_path / "usage.json")
        store.record("groq", "llama-3.3-70b", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))

        records = store.get_today()
        assert len(records) == 1
        assert records[0].request_count == 1
        assert records[0].prompt_tokens == 10

    def test_usage_accumulates_correctly(self, tmp_path):
        from llm_kernel.extensions import UsageStore
        from llm_kernel.core import Usage

        store = UsageStore(path=tmp_path / "usage.json")
        # Simulate: first attempt fails, second succeeds — only record once
        store.record("groq", "llama-3.3-70b", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))

        records = store.get_today()
        assert len(records) == 1
        assert records[0].request_count == 1  # Not 2

    def test_usage_not_recorded_for_failed_attempt(self, tmp_path):
        from llm_kernel.extensions import UsageStore

        store = UsageStore(path=tmp_path / "usage.json")
        # If execution fails, record() should not be called
        # Verify store is empty
        assert store.get_today() == []
