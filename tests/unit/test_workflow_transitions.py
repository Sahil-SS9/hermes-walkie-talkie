"""Workflow transition tests (P5.3, G4.3, G4.7)."""

from __future__ import annotations

import pytest

from agent_peer.workflows import (
    InvalidTransition,
    RequestState,
    can_transition,
    is_terminal,
    transition,
)

C = RequestState.CREATED
Q = RequestState.QUEUED
A = RequestState.ACCEPTED
P = RequestState.IN_PROGRESS
D = RequestState.COMPLETED
F = RequestState.FAILED
R = RequestState.REFUSED
X = RequestState.CANCELLED
E = RequestState.EXPIRED


def test_happy_path_created_to_completed():
    assert transition(C, Q) == Q
    assert transition(Q, A) == A
    assert transition(A, P) == P
    assert transition(P, D) == D


def test_refuse_and_fail_paths():
    assert transition(Q, R) == R
    assert transition(A, F) == F
    assert transition(P, F) == F


def test_cancel_is_advisory_everywhere_before_terminal():
    assert transition(C, X) == X
    assert transition(Q, X) == X
    assert transition(A, X) == X
    assert transition(P, X) == X


def test_expiry_paths():
    assert transition(C, E) == E
    assert transition(Q, E) == E
    assert transition(P, E) == E


def test_terminal_states_are_terminal():
    for s in (D, F, R, X, E):
        assert is_terminal(s)
    assert not is_terminal(C)
    assert not is_terminal(P)


def test_impossible_transitions_rejected():
    # Skipping states is impossible.
    with pytest.raises(InvalidTransition):
        transition(C, P)
    with pytest.raises(InvalidTransition):
        transition(Q, D)
    # Terminal -> anything is impossible.
    for t in (Q, A, P, D, F, R, X, E):
        with pytest.raises(InvalidTransition):
            transition(D, t)
        with pytest.raises(InvalidTransition):
            transition(X, t)
    # Going backwards is impossible.
    with pytest.raises(InvalidTransition):
        transition(A, Q)
    with pytest.raises(InvalidTransition):
        transition(P, A)


def test_completed_never_leaves_terminal():
    assert can_transition(D, D) is False
    assert can_transition(D, P) is False
    assert can_transition(C, Q) is True


def test_accept_requires_queued():
    assert can_transition(C, A) is False
    assert can_transition(Q, A) is True


def test_string_state_accepted():
    assert transition("created", "queued") == Q
    assert can_transition("in_progress", "completed") is True
