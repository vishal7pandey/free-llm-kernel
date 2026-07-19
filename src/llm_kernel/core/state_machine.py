"""Request state machine for tracking execution lifecycle.

Implements DVM X-05: terminal states are absorbing — once a request reaches
COMPLETED, FAILED, CANCELLED, or TIMED_OUT, no further transitions are allowed.
"""

from __future__ import annotations

from enum import StrEnum

from llm_kernel.core import KernelError


class RequestState(StrEnum):
    PENDING = "pending"
    PLANNED = "planned"
    EXECUTING = "executing"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATES: frozenset[RequestState] = frozenset(
    {
        RequestState.COMPLETED,
        RequestState.FAILED,
        RequestState.CANCELLED,
        RequestState.TIMED_OUT,
    }
)

_ALLOWED_TRANSITIONS: dict[RequestState, frozenset[RequestState]] = {
    RequestState.PENDING: frozenset({RequestState.PLANNED, RequestState.CANCELLED}),
    RequestState.PLANNED: frozenset(
        {
            RequestState.EXECUTING,
            RequestState.CANCELLED,
            RequestState.FAILED,
        }
    ),
    RequestState.EXECUTING: frozenset(
        {
            RequestState.STREAMING,
            RequestState.COMPLETED,
            RequestState.FAILED,
            RequestState.TIMED_OUT,
            RequestState.CANCELLED,
        }
    ),
    RequestState.STREAMING: frozenset(
        {
            RequestState.COMPLETED,
            RequestState.FAILED,
            RequestState.TIMED_OUT,
            RequestState.CANCELLED,
        }
    ),
    RequestState.COMPLETED: frozenset(),
    RequestState.FAILED: frozenset(),
    RequestState.CANCELLED: frozenset(),
    RequestState.TIMED_OUT: frozenset(),
}


class InvalidStateTransition(KernelError):  # noqa: N818
    """Raised when an illegal state transition is attempted."""


class RequestStateMachine:
    """Tracks the state of a single request through its lifecycle.

    Terminal states are absorbing: once reached, any further transition
    raises InvalidStateTransition.
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._state: RequestState = RequestState.PENDING

    @property
    def state(self) -> RequestState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def transition_to(self, target: RequestState) -> None:
        if self._state in TERMINAL_STATES:
            raise InvalidStateTransition(
                f"Cannot transition from terminal state {self._state.value} "
                f"to {target.value} (trace_id={self.trace_id})"
            )
        allowed = _ALLOWED_TRANSITIONS.get(self._state, frozenset())
        if target not in allowed:
            raise InvalidStateTransition(
                f"Cannot transition from {self._state.value} to {target.value} "
                f"(trace_id={self.trace_id}). Allowed: {sorted(s.value for s in allowed)}"
            )
        self._state = target

    def can_transition_to(self, target: RequestState) -> bool:
        if self._state in TERMINAL_STATES:
            return False
        return target in _ALLOWED_TRANSITIONS.get(self._state, frozenset())


__all__ = [
    "RequestState",
    "RequestStateMachine",
    "InvalidStateTransition",
    "TERMINAL_STATES",
]
