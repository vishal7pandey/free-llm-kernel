"""API stability test — freezes the public API surface for v0.9.

This test snapshots the public exports of the llm_kernel package and all
major submodules. If the API surface changes, this test fails, forcing
a conscious decision about backward compatibility.

To update the snapshot after an intentional API change, update the
frozensets below and document the change in CHANGELOG.md.
"""

import llm_kernel

# ---------------------------------------------------------------------------
# Frozen public API surface (v0.9)
# ---------------------------------------------------------------------------

EXPECTED_TOP_LEVEL_EXPORTS = frozenset({
    "__version__",
    "LLMClient",
    "ModelInfo",
    "Extension",
    "MiddlewareChain",
    "BestFreePolicy",
    "Capability",
    "CAPABILITY_ALIASES",
    "ErrorCategory",
    "ExecutionError",
    "ExecutionPlan",
    "FinishReason",
    "FunctionCall",
    "FunctionTool",
    "KernelError",
    "Message",
    "ModelMetadata",
    "ProviderMetadata",
    "PlanningError",
    "Candidate",
    "FallbackPolicy",
    "RetryPolicy",
    "RoutingPolicy",
    "TimeoutPolicy",
    "infer_capabilities",
    "infer_model_metadata",
    "PolicyPlugin",
    "PluginRegistry",
    "ProviderPlugin",
    "get_registry",
    "load_plugins",
    "register_policy_plugin",
    "register_provider_plugin",
    "Request",
    "Response",
    "ResponseFormat",
    "Role",
    "Secret",
    "Tool",
    "ToolCall",
    "Usage",
    "ValidationError",
    "resolve_capabilities",
})

EXPECTED_CORE_EXPORTS = frozenset({
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
})

EXPECTED_PLANNER_EXPORTS = frozenset({
    "TokenEstimator",
    "DefaultTokenEstimator",
    "WorldState",
    "ProviderCatalogue",
    "HealthSnapshot",
    "QuotaSnapshot",
    "RoutingPolicy",
    "DefaultRoutingPolicy",
    "BestFreePolicy",
    "FastestPolicy",
    "CheapestPolicy",
    "QualityPolicy",
    "POLICY_REGISTRY",
    "resolve_policy",
    "infer_capabilities",
    "infer_context_tokens",
    "infer_quality_score",
    "infer_model_metadata",
    "Planner",
    "PlanningError",
    "Candidate",
    "ExecutionPlan",
    "FallbackPolicy",
    "TimeoutPolicy",
    "RetryPolicy",
    "ModelMetadata",
    "ProviderMetadata",
})

EXPECTED_RUNTIME_EXPORTS = frozenset({
    "AdapterConfig",
    "Attempt",
    "ExecutionResult",
    "CircuitBreaker",
    "HealthTracker",
    "RetryEngine",
    "Adapter",
    "OpenAICompatibleAdapter",
    "Executor",
})

EXPECTED_EXTENSIONS_EXPORTS = frozenset({
    "Extension",
    "ExtensionError",
    "MiddlewareChain",
    "UsageStore",
})

EXPECTED_PLUGINS_EXPORTS = frozenset({
    "ProviderPlugin",
    "PolicyPlugin",
    "PluginRegistry",
    "get_registry",
    "register_provider_plugin",
    "register_policy_plugin",
    "load_plugins",
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAPIStability:
    def test_top_level_exports_frozen(self):
        actual = set(llm_kernel.__all__)
        expected = set(EXPECTED_TOP_LEVEL_EXPORTS)
        assert actual == expected, (
            f"Top-level API surface changed!\n"
            f"  Added: {actual - expected}\n"
            f"  Removed: {expected - actual}\n"
            f"If intentional, update EXPECTED_TOP_LEVEL_EXPORTS and CHANGELOG."
        )

    def test_core_exports_frozen(self):
        from llm_kernel import core

        actual = set(core.__all__)
        expected = set(EXPECTED_CORE_EXPORTS)
        assert actual == expected, (
            f"Core API surface changed!\n"
            f"  Added: {actual - expected}\n"
            f"  Removed: {expected - actual}\n"
            f"If intentional, update EXPECTED_CORE_EXPORTS and CHANGELOG."
        )

    def test_planner_exports_frozen(self):
        from llm_kernel import planner

        actual = set(planner.__all__)
        expected = set(EXPECTED_PLANNER_EXPORTS)
        assert actual == expected, (
            f"Planner API surface changed!\n"
            f"  Added: {actual - expected}\n"
            f"  Removed: {expected - actual}\n"
            f"If intentional, update EXPECTED_PLANNER_EXPORTS and CHANGELOG."
        )

    def test_runtime_exports_frozen(self):
        from llm_kernel import runtime

        actual = set(runtime.__all__)
        expected = set(EXPECTED_RUNTIME_EXPORTS)
        assert actual == expected, (
            f"Runtime API surface changed!\n"
            f"  Added: {actual - expected}\n"
            f"  Removed: {expected - actual}\n"
            f"If intentional, update EXPECTED_RUNTIME_EXPORTS and CHANGELOG."
        )

    def test_extensions_exports_frozen(self):
        from llm_kernel import extensions

        actual = set(extensions.__all__)
        expected = set(EXPECTED_EXTENSIONS_EXPORTS)
        assert actual == expected, (
            f"Extensions API surface changed!\n"
            f"  Added: {actual - expected}\n"
            f"  Removed: {expected - actual}\n"
            f"If intentional, update EXPECTED_EXTENSIONS_EXPORTS and CHANGELOG."
        )

    def test_plugins_exports_frozen(self):
        from llm_kernel import plugins

        actual = set(plugins.__all__)
        expected = set(EXPECTED_PLUGINS_EXPORTS)
        assert actual == expected, (
            f"Plugins API surface changed!\n"
            f"  Added: {actual - expected}\n"
            f"  Removed: {expected - actual}\n"
            f"If intentional, update EXPECTED_PLUGINS_EXPORTS and CHANGELOG."
        )

    def test_version_is_string(self):
        assert isinstance(llm_kernel.__version__, str)
        assert llm_kernel.__version__ == "0.9.0"

    def test_all_exports_are_importable(self):
        """Every name in __all__ must be importable from the top-level package."""
        for name in llm_kernel.__all__:
            assert hasattr(llm_kernel, name), (
                f"'{name}' is in __all__ but not importable from llm_kernel"
            )

    def test_public_methods_on_llmclient(self):
        """Verify LLMClient's public method signatures are stable."""
        from llm_kernel import LLMClient

        expected_methods = {
            "chat",
            "stream",
            "execute",
            "available_providers",
            "usage",
            "models",
            "get_model",
            "list_providers",
            "cheapest_model",
            "fastest_model",
            "best_model",
            "add_provider",
            "register_policy",
            "available_policies",
            "refresh_models",
            "provider_health",
            "from_env",
        }
        actual_methods = {
            name
            for name in dir(LLMClient)
            if not name.startswith("_") and callable(getattr(LLMClient, name, None))
        }
        missing = expected_methods - actual_methods
        assert not missing, f"LLMClient missing public methods: {missing}"
