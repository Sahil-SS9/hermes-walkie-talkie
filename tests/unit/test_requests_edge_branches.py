"""RequestStore edge branches (P11.1 coverage)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_peer.requests import RequestStore
from agent_peer.store import MessageStore

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _store() -> tuple[MessageStore, RequestStore]:
    ms = MessageStore(Path(tempfile.mkdtemp()) / "r.sqlite3")
    return ms, RequestStore(ms)


class TestRequestStoreBranches:
    def test_get_missing_returns_none(self):
        _, rs = _store()
        assert rs.get("no-such-id") is None

    def test_list_for_recipient_state_filter(self):
        _, rs = _store()
        req = rs.create(
            sender_agent_id=A,
            recipient_agent_id=B,
            summary="s",
            deadline="2099-01-01T00:00:00+00:00",
            payload={},
            idempotency_key="k1",
        )
        all_rows = rs.list_for_recipient(B)
        created_rows = rs.list_for_recipient(B, states=("created",))
        done_rows = rs.list_for_recipient(B, states=("completed",))
        assert len(all_rows) == 1
        assert len(created_rows) == 1
        assert done_rows == []

    def test_transition_missing_returns_none(self):
        _, rs = _store()
        assert rs.transition("no-such-id", "accepted") is None
