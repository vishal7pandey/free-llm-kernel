"""Tests for RequestStateMachine.

Covers DVM X-05: terminal states are absorbing.
"""

import pytest

from llm_kernel.core import (
    InvalidStateTransition,
    RequestState,
    RequestStateMachine,
    TERMINAL_STATES,
)


class TestRequestStateMachine:
    def test_initial_state_is_pending(self):
        sm = RequestStateMachine(trace_id="t1")
        assert sm.state == RequestState.PENDING
        assert sm.is_terminal is False

    def test_valid_transition_pending_to_planned(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        assert sm.state == RequestState.PLANNED

    def test_valid_full_lifecycle(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.EXECUTING)
        sm.transition_to(RequestState.COMPLETED)
        assert sm.state == RequestState.COMPLETED
        assert sm.is_terminal is True

    def test_valid_streaming_lifecycle(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.EXECUTING)
        sm.transition_to(RequestState.STREAMING)
        sm.transition_to(RequestState.COMPLETED)
        assert sm.is_terminal is True

    def test_cancelled_from_pending(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.CANCELLED)
        assert sm.is_terminal is True

    def test_cancelled_from_planned(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.CANCELLED)
        assert sm.is_terminal is True

    def test_failed_from_executing(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.EXECUTING)
        sm.transition_to(RequestState.FAILED)
        assert sm.is_terminal is True

    def test_timed_out_from_executing(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.EXECUTING)
        sm.transition_to(RequestState.TIMED_OUT)
        assert sm.is_terminal is True

    @pytest.mark.parametrize("terminal", list(TERMINAL_STATES))
    def test_terminal_state_is_absorbing(self, terminal):
        sm = RequestStateMachine(trace_id="t1")
        # Force into terminal state via valid path
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.EXECUTING)
        sm.transition_to(terminal)
        assert sm.is_terminal is True
        # Any further transition must fail
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(RequestState.EXECUTING)
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(RequestState.COMPLETED)

    def test_invalid_transition_raises(self):
        sm = RequestStateMachine(trace_id="t1")
        # PENDING -> EXECUTING is not allowed (must go through PLANNED)
        with pytest.raises(InvalidStateTransition) as exc_info:
            sm.transition_to(RequestState.EXECUTING)
        assert "pending" in str(exc_info.value).lower()
        assert "executing" in str(exc_info.value).lower()

    def test_invalid_transition_pending_to_completed(self):
        sm = RequestStateMachine(trace_id="t1")
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(RequestState.COMPLETED)

    def test_invalid_transition_streaming_to_planned(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.EXECUTING)
        sm.transition_to(RequestState.STREAMING)
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(RequestState.PLANNED)

    def test_can_transition_to_valid(self):
        sm = RequestStateMachine(trace_id="t1")
        assert sm.can_transition_to(RequestState.PLANNED) is True
        assert sm.can_transition_to(RequestState.CANCELLED) is True

    def test_can_transition_to_invalid(self):
        sm = RequestStateMachine(trace_id="t1")
        assert sm.can_transition_to(RequestState.EXECUTING) is False
        assert sm.can_transition_to(RequestState.COMPLETED) is False

    def test_can_transition_to_false_in_terminal(self):
        sm = RequestStateMachine(trace_id="t1")
        sm.transition_to(RequestState.PLANNED)
        sm.transition_to(RequestState.EXECUTING)
        sm.transition_to(RequestState.COMPLETED)
        assert sm.can_transition_to(RequestState.EXECUTING) is False
        assert sm.can_transition_to(RequestState.PENDING) is False

    def test_all_terminal_states(self):
        assert len(TERMINAL_STATES) == 4
        assert RequestState.COMPLETED in TERMINAL_STATES
        assert RequestState.FAILED in TERMINAL_STATES
        assert RequestState.CANCELLED in TERMINAL_STATES
        assert RequestState.TIMED_OUT in TERMINAL_STATES
        # Non-terminal states
        assert RequestState.PENDING not in TERMINAL_STATES
        assert RequestState.PLANNED not in TERMINAL_STATES
        assert RequestState.EXECUTING not in TERMINAL_STATES
        assert RequestState.STREAMING not in TERMINAL_STATES
