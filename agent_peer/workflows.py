"""Workflow state-machine decision table (P5.3, G4.3, ADR-0004).

Pure transition function:
``created -> queued -> accepted -> in_progress -> completed|failed|refused|cancelled|expired``

The transition is a strict decision table — impossible, stale, out-of-order
and cross-request responses are rejected (G4.3, P5.7). This module has NO
I/O; it is the single source of truth for what transitions are legal.
"""

from __future__ import annotations

from enum import Enum


class RequestState(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# Legal transitions, keyed (from, to) -> reason label.
_TRANSITIONS: dict[tuple[RequestState, RequestState], str] = {
    (RequestState.CREATED, RequestState.QUEUED): "enqueue",
    (RequestState.CREATED, RequestState.CANCELLED): "cancel_before_delivery",
    (RequestState.CREATED, RequestState.EXPIRED): "expiry",
    (RequestState.QUEUED, RequestState.ACCEPTED): "accept",
    (RequestState.QUEUED, RequestState.REFUSED): "refuse",
    (RequestState.QUEUED, RequestState.CANCELLED): "cancel_before_accept",
    (RequestState.QUEUED, RequestState.EXPIRED): "expiry",
    (RequestState.ACCEPTED, RequestState.IN_PROGRESS): "progress",
    (RequestState.ACCEPTED, RequestState.CANCELLED): "cancel_before_start",
    (RequestState.ACCEPTED, RequestState.FAILED): "fail_before_start",
    (RequestState.ACCEPTED, RequestState.EXPIRED): "expiry",
    (RequestState.IN_PROGRESS, RequestState.COMPLETED): "complete",
    (RequestState.IN_PROGRESS, RequestState.FAILED): "fail",
    (RequestState.IN_PROGRESS, RequestState.CANCELLED): "cancel_advisory",
    (RequestState.IN_PROGRESS, RequestState.EXPIRED): "expiry",
    # Terminal states: no further transitions.
}

_TERMINAL = frozenset(
    {
        RequestState.COMPLETED,
        RequestState.FAILED,
        RequestState.REFUSED,
        RequestState.CANCELLED,
        RequestState.EXPIRED,
    }
)


class InvalidTransition(Exception):
    """The requested transition is impossible in the current state."""


def can_transition(state: RequestState | str, target: RequestState | str) -> bool:
    s = state if isinstance(state, RequestState) else RequestState(state)
    t = target if isinstance(target, RequestState) else RequestState(target)
    return (s, t) in _TRANSITIONS


def transition(state: RequestState | str, target: RequestState | str) -> RequestState:
    """Return the target state iff the transition is legal; else raise."""
    s = state if isinstance(state, RequestState) else RequestState(state)
    t = target if isinstance(target, RequestState) else RequestState(target)
    if (s, t) not in _TRANSITIONS:
        reason = _TRANSITIONS.get((s, t))
        raise InvalidTransition(
            f"illegal request transition {s.value} -> {t.value}"
            + (f" ({reason})" if reason else "")
        )
    return t


def is_terminal(state: RequestState | str) -> bool:
    s = state if isinstance(state, RequestState) else RequestState(state)
    return s in _TERMINAL


__all__ = ["InvalidTransition", "RequestState", "can_transition", "is_terminal", "transition"]
