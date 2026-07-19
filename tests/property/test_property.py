"""Property-based tests for core invariants using Hypothesis.

Tests:
- State machine: terminal states are absorbing, valid transitions succeed
- Capability resolution: always returns frozenset, aliases map correctly
- Token estimation: monotonic with content length, always >= 1
- Planner determinism: same input → same output
- Model discovery inference: STREAMING always present, metadata is valid
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from llm_kernel.core import (
    CAPABILITY_ALIASES,
    Capability,
    Message,
    Request,
    Role,
    resolve_capabilities,
)
from llm_kernel.core.state_machine import (
    TERMINAL_STATES,
    InvalidStateTransition,
    RequestState,
    RequestStateMachine,
)
from llm_kernel.planner import (
    DefaultTokenEstimator,
    ModelMetadata,
    Planner,
    ProviderMetadata,
    WorldState,
    infer_capabilities,
    infer_context_tokens,
    infer_model_metadata,
    infer_quality_score,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

states = st.sampled_from(list(RequestState))
terminal_states = st.sampled_from(list(TERMINAL_STATES))
non_terminal_states = st.sampled_from(
    [s for s in RequestState if s not in TERMINAL_STATES]
)
capabilities = st.sampled_from(list(Capability))
alias_strings = st.sampled_from(list(CAPABILITY_ALIASES.keys()))
capability_values = st.sampled_from(list(Capability))
roles = st.sampled_from(list(Role))
text = st.text(min_size=0, max_size=500)
non_empty_text = st.text(min_size=1, max_size=500, alphabet=st.characters(
    whitelist_categories=("Ll", "Lu", "Nd", "Pc", "Pd", "Po", "Ps", "Pe", "Pi", "Pf", "Sm", "Sc"),
))
model_ids = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"),
    whitelist_characters="-._/",
))


# ---------------------------------------------------------------------------
# State Machine Properties
# ---------------------------------------------------------------------------


class TestStateMachineProperties:
    @given(state=terminal_states, target=states)
    @settings(max_examples=100)
    def test_terminal_state_absorbing(self, state: RequestState, target: RequestState):
        """Once in a terminal state, no transition is allowed."""
        sm = RequestStateMachine("trace-1")
        # Force the state by walking through a valid path
        sm._state = state
        assert sm.is_terminal
        assert not sm.can_transition_to(target)
        try:
            sm.transition_to(target)
            raise AssertionError(f"Transition from {state} to {target} should have raised")
        except InvalidStateTransition:
            pass

    @given(state=non_terminal_states)
    @settings(max_examples=50)
    def test_non_terminal_not_absorbing(self, state: RequestState):
        """Non-terminal states should allow at least one transition."""
        sm = RequestStateMachine("trace-1")
        sm._state = state
        assert not sm.is_terminal
        # At least one target should be valid
        assert any(sm.can_transition_to(t) for t in RequestState)

    @given(state=non_terminal_states, target=states)
    @settings(max_examples=200)
    def test_can_transition_to_matches_transition_to(
        self, state: RequestState, target: RequestState,
    ):
        """can_transition_to() and transition_to() must agree."""
        sm = RequestStateMachine("trace-1")
        sm._state = state
        can = sm.can_transition_to(target)
        if can:
            sm.transition_to(target)
            assert sm.state == target
        else:
            try:
                sm.transition_to(target)
                raise AssertionError("transition_to should have raised")
            except InvalidStateTransition:
                pass

    @given(target=states)
    @settings(max_examples=50)
    def test_initial_state_is_pending(self, target: RequestState):
        """Fresh state machine starts in PENDING."""
        sm = RequestStateMachine("trace-1")
        assert sm.state == RequestState.PENDING
        assert not sm.is_terminal


# ---------------------------------------------------------------------------
# Capability Resolution Properties
# ---------------------------------------------------------------------------


class TestCapabilityResolutionProperties:
    @given(cap=capabilities)
    @settings(max_examples=50)
    def test_single_capability_returns_frozenset(self, cap: Capability):
        """Resolving a single Capability returns a frozenset containing it."""
        result = resolve_capabilities(cap)
        assert isinstance(result, frozenset)
        assert cap in result
        assert len(result) == 1

    @given(alias=alias_strings)
    @settings(max_examples=50)
    def test_alias_resolves_to_valid_capability(self, alias: str):
        """Every alias in CAPABILITY_ALIASES resolves to a valid Capability."""
        result = resolve_capabilities(alias)
        assert isinstance(result, frozenset)
        assert len(result) == 1
        expected = CAPABILITY_ALIASES[alias]
        assert expected in result

    @given(caps=st.lists(capability_values, min_size=0, max_size=10))
    @settings(max_examples=50)
    def test_list_resolution_returns_frozenset(self, caps: list[Capability]):
        """Resolving a list of capabilities returns a frozenset."""
        result = resolve_capabilities(caps)
        assert isinstance(result, frozenset)
        assert result == frozenset(caps)

    @given(caps=st.lists(alias_strings, min_size=0, max_size=10))
    @settings(max_examples=50)
    def test_list_of_aliases_resolves_correctly(self, caps: list[str]):
        """Resolving a list of alias strings returns the correct frozenset."""
        result = resolve_capabilities(caps)
        expected = frozenset(CAPABILITY_ALIASES[c] for c in caps)
        assert result == expected

    def test_none_returns_empty_frozenset(self):
        """None input returns empty frozenset."""
        result = resolve_capabilities(None)
        assert result == frozenset()
        assert isinstance(result, frozenset)

    @given(caps=st.lists(st.one_of(capability_values, alias_strings), min_size=0, max_size=20))
    @settings(max_examples=100)
    def test_mixed_list_resolution(self, caps: list):
        """Mixing Capability enums and alias strings resolves correctly."""
        result = resolve_capabilities(caps)
        assert isinstance(result, frozenset)
        expected: set[Capability] = set()
        for c in caps:
            if isinstance(c, Capability):
                expected.add(c)
            else:
                expected.add(CAPABILITY_ALIASES[c])
        assert result == frozenset(expected)

    @given(alias=alias_strings)
    @settings(max_examples=50)
    def test_case_insensitive_resolution(self, alias: str):
        """Resolution is case-insensitive."""
        result_lower = resolve_capabilities(alias.lower())
        result_upper = resolve_capabilities(alias.upper())
        result_mixed = resolve_capabilities(alias.capitalize())
        assert result_lower == result_upper == result_mixed


# ---------------------------------------------------------------------------
# Token Estimation Properties
# ---------------------------------------------------------------------------


class TestTokenEstimationProperties:
    estimator = DefaultTokenEstimator()

    @given(content=text)
    @settings(max_examples=100)
    def test_estimate_content_always_positive(self, content: str):
        """Token estimate is always >= 1 for any string."""
        result = self.estimator.estimate_content(content)
        assert result >= 1

    @given(
        content_a=text,
        content_b=text,
    )
    @settings(max_examples=100)
    def test_monotonic_with_concatenation(self, content_a: str, content_b: str):
        """Estimate(a + b) >= estimate(a)."""
        est_a = self.estimator.estimate_content(content_a)
        est_ab = self.estimator.estimate_content(content_a + content_b)
        assert est_ab >= est_a

    @given(messages=st.lists(
        st.builds(Message, role=roles, content=non_empty_text),
        min_size=1,
        max_size=10,
    ))
    @settings(max_examples=50)
    def test_estimate_messages_always_positive(self, messages: list[Message]):
        """Token estimate for messages is always >= 1."""
        result = self.estimator.estimate_messages(messages)
        assert result >= 1

    @given(
        messages_a=st.lists(
            st.builds(Message, role=roles, content=non_empty_text),
            min_size=1,
            max_size=5,
        ),
        messages_b=st.lists(
            st.builds(Message, role=roles, content=non_empty_text),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=50)
    def test_estimate_messages_monotonic(
        self, messages_a: list[Message], messages_b: list[Message],
    ):
        """More messages → same or higher token estimate."""
        est_a = self.estimator.estimate_messages(messages_a)
        est_ab = self.estimator.estimate_messages(messages_a + messages_b)
        assert est_ab >= est_a


# ---------------------------------------------------------------------------
# Model Discovery Inference Properties
# ---------------------------------------------------------------------------


class TestModelDiscoveryProperties:
    @given(model_id=model_ids)
    @settings(max_examples=100)
    def test_inferred_capabilities_always_include_streaming(self, model_id: str):
        """STREAMING is always inferred for any model on OpenAI-compatible endpoints."""
        caps = infer_capabilities(model_id)
        assert Capability.STREAMING in caps

    @given(model_id=model_ids)
    @settings(max_examples=100)
    def test_inferred_capabilities_returns_frozenset(self, model_id: str):
        """infer_capabilities always returns a frozenset."""
        caps = infer_capabilities(model_id)
        assert isinstance(caps, frozenset)

    @given(model_id=model_ids)
    @settings(max_examples=100)
    def test_inferred_context_tokens_positive(self, model_id: str):
        """Context token estimate is always > 0."""
        tokens = infer_context_tokens(model_id)
        assert tokens > 0
        assert tokens >= 2048

    @given(model_id=model_ids)
    @settings(max_examples=100)
    def test_inferred_quality_score_in_range(self, model_id: str):
        """Quality score is always in [0.0, 1.0]."""
        score = infer_quality_score(model_id)
        assert 0.0 <= score <= 1.0

    @given(model_id=model_ids)
    @settings(max_examples=100)
    def test_inferred_metadata_is_valid(self, model_id: str):
        """infer_model_metadata returns a valid ModelMetadata."""
        meta = infer_model_metadata(model_id)
        assert isinstance(meta, ModelMetadata)
        assert meta.id == model_id
        assert meta.max_context_tokens > 0
        assert 0.0 <= meta.quality_score <= 1.0
        assert 0.0 <= meta.latency_score <= 1.0
        assert Capability.STREAMING in meta.capabilities

    @given(model_id=model_ids)
    @settings(max_examples=50)
    def test_inference_is_deterministic(self, model_id: str):
        """Same model ID always produces the same inferred metadata."""
        meta1 = infer_model_metadata(model_id)
        meta2 = infer_model_metadata(model_id)
        assert meta1 == meta2


# ---------------------------------------------------------------------------
# Planner Determinism Properties
# ---------------------------------------------------------------------------


def _make_test_provider() -> ProviderMetadata:
    return ProviderMetadata(
        name="mock",
        display_name="Mock",
        adapter_type="openai",
        base_url="https://api.mock.com/v1",
        api_key_env="MOCK_API_KEY",
        models=[
            ModelMetadata(
                id="model-a",
                display_name="Model A",
                max_context_tokens=8192,
                capabilities=frozenset({Capability.STREAMING, Capability.TOOLS}),
                quality_score=0.7,
                latency_score=0.8,
            ),
            ModelMetadata(
                id="model-b",
                display_name="Model B",
                max_context_tokens=32768,
                capabilities=frozenset({Capability.STREAMING, Capability.VISION}),
                quality_score=0.6,
                latency_score=0.9,
            ),
        ],
        default_model="model-a",
        daily_request_limit=1000,
    )


class TestPlannerDeterminism:
    @given(
        content=non_empty_text,
        temp=st.floats(min_value=0.0, max_value=2.0),
        max_tokens=st.integers(min_value=1, max_value=4096),
    )
    @settings(max_examples=50)
    def test_same_input_same_output(self, content: str, temp: float, max_tokens: int):
        """Planner.plan() is deterministic: same input → same output."""
        provider = _make_test_provider()
        ws = WorldState(providers=[provider])
        planner = Planner(ws)

        request = Request(
            messages=[Message(role=Role.USER, content=content)],
            temperature=temp,
            max_tokens=max_tokens,
        )

        plan1 = planner.plan(request)
        plan2 = planner.plan(request)

        assert plan1.trace_id == plan2.trace_id
        assert len(plan1.candidates) == len(plan2.candidates)
        for c1, c2 in zip(plan1.candidates, plan2.candidates, strict=False):
            assert c1.provider == c2.provider
            assert c1.model == c2.model
            assert c1.score == c2.score

    @given(
        content=non_empty_text,
    )
    @settings(max_examples=50)
    def test_candidates_sorted_by_score(self, content: str):
        """Plan candidates are always sorted by descending score."""
        provider = _make_test_provider()
        ws = WorldState(providers=[provider])
        planner = Planner(ws)

        request = Request(
            messages=[Message(role=Role.USER, content=content)],
        )

        plan = planner.plan(request)
        scores = [c.score for c in plan.candidates]
        assert scores == sorted(scores, reverse=True)
