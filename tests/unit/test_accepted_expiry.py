"""CAREFUL-2: accepted requests must expire past deadline.

Repro at final SHA ffe3687: an accepted request past deadline remains
accepted; expired count is 0. Required:
- accepted → expired is a legal transition,
- expire_overdue includes accepted requests,
- expiry is bounded to non-terminal states.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_peer.request_models import RequestState
from agent_peer.requests import RequestStore
from agent_peer.store import MessageStore
from agent_peer.workflows import can_transition, transition

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _rs() -> RequestStore:
    return RequestStore(MessageStore(Path(tempfile.mkdtemp()) / "r.sqlite3"))


class TestAcceptedExpiry:
    def test_accepted_expired_is_legal(self):
        assert can_transition(RequestState.ACCEPTED, RequestState.EXPIRED)
        assert transition(RequestState.ACCEPTED, RequestState.EXPIRED) == RequestState.EXPIRED

    def test_expire_overdue_includes_accepted(self):
        rs = _rs()
        req = rs.create(
            sender_agent_id=A,
            recipient_agent_id=B,
            summary="s",
            deadline="2000-01-01T00:00:00+00:00",
            idempotency_key="k1",
        )
        # Move to accepted (created -> queued -> accepted).
        rs.transition(req.request_id, "queued")
        rs.transition(req.request_id, "accepted")
        assert rs.get(req.request_id).state == "accepted"
        n = rs.expire_overdue(now="2099-01-01T00:00:00+00:00")
        assert n == 1
        assert rs.get(req.request_id).state == "expired"

    def test_future_deadline_not_expired(self):
        rs = _rs()
        req = rs.create(
            sender_agent_id=A,
            recipient_agent_id=B,
            summary="s",
            deadline="2099-01-01T00:00:00+00:00",
            idempotency_key="k2",
        )
        rs.transition(req.request_id, "queued")
        rs.transition(req.request_id, "accepted")
        assert rs.expire_overdue(now="2000-01-01T00:00:00+00:00") == 0
        assert rs.get(req.request_id).state == "accepted"

    def test_terminal_states_not_expired(self):
        rs = _rs()
        req = rs.create(
            sender_agent_id=A,
            recipient_agent_id=B,
            summary="s",
            deadline="2000-01-01T00:00:00+00:00",
            idempotency_key="k3",
        )
        for target in ("queued", "accepted", "in_progress", "completed"):
            rs.transition(req.request_id, target)
        assert rs.get(req.request_id).state == "completed"
        assert rs.expire_overdue(now="2099-01-01T00:00:00+00:00") == 0
        assert rs.get(req.request_id).state == "completed"
