"""RED tests for duplicate-receipt transactional dedup (F-06, REM-401..403).

The plan §4.6 contract: BEFORE policy evaluation or host delivery, look up
``message_id`` under the same store lock/transaction:

- if present, return the exact original persisted ``ReceiptState`` and
  recipient;
- do NOT re-evaluate policy;
- do NOT inject again;
- do NOT transition a prior ``queued``/``held``/``refused`` or failure state;
- concurrent duplicates converge on one row, one host injection and one
  state.
"""

from __future__ import annotations

import threading
import uuid

import pytest

from agent_peer.models import Envelope, PeerIdentity, ReceiptState
from hermes_peer.plugin import get_manager, register


class FakeCtx:
    def __init__(self) -> None:
        self.hooks: dict[str, list] = {}
        self.tools: dict[str, dict] = {}
        self.injected: list[tuple] = []

    def register_hook(self, name, callback) -> None:
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, name, toolset, schema, handler, **kw) -> None:
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_command(self, *a, **kw) -> None:
        pass

    def register_cli_command(self, *a, **kw) -> None:
        pass

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        self.injected.append((content, role, mode, target_session))
        return True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    ctx = FakeCtx()
    register(ctx)
    yield ctx
    mgr = get_manager()
    if mgr is not None:
        mgr.shutdown()
        from hermes_peer import plugin

        plugin._manager = None


def _envelope(mgr, recipient_peer_id: str, content: str, message_id: str | None = None) -> Envelope:
    from agent_peer.models import make_envelope

    sender = PeerIdentity(peer_id=mgr._peers[list(mgr._peers)[0]].peer_id, name="a", profile="")
    return make_envelope(
        sender=sender,
        recipient_peer_id=recipient_peer_id,
        content=content,
        message_id=message_id or str(uuid.uuid4()),
    )


class TestSequentialDuplicate:
    """REM-401: a duplicate message_id after each persisted state returns the
    original state with one row and one host injection."""

    def _insert_one(self, env, mgr, state: str, content: str) -> Envelope:

        recipient = mgr._peers[list(mgr._peers)[0]]
        e = _envelope(mgr, recipient.peer_id, content)
        mgr._store.record(
            {
                "message_id": e.message_id,
                "recipient_peer_id": e.recipient_peer_id,
                "sender_peer_id": e.sender.peer_id,
                "kind": e.kind.value,
                "content": e.content,
                "state": state,
                "created_at": e.created_at.isoformat(),
                "expires_at": e.expires_at.isoformat(),
                "reply_to": e.reply_to,
                "conversation_id": e.conversation_id,
                "delivered_at": None,
                "hop_count": e.hop_count,
            }
        )
        return e

    def test_duplicate_after_held_returns_held_no_reinject(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        e = self._insert_one(env, mgr, ReceiptState.HELD.value, "held once")
        before = len(mgr._ctx.injected)
        # Re-deliver the same message through the full inbound pipeline.
        state = mgr._on_inbound(e)
        assert state == ReceiptState.HELD
        assert len(mgr._ctx.injected) == before  # no second inject
        row = mgr._store.get(e.message_id)
        assert row["state"] == ReceiptState.HELD.value  # state not transitioned

    def test_duplicate_after_queued_returns_queued_no_reinject(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        recipient = mgr._peers["sess-a"]
        e = _envelope(mgr, recipient.peer_id, "queued once")
        state = mgr._on_inbound(e)  # accept -> queued, injects once
        assert state == ReceiptState.QUEUED
        assert len(mgr._ctx.injected) == 1
        # Duplicate: must NOT inject again and must return queued.
        state2 = mgr._on_inbound(e)
        assert state2 == ReceiptState.QUEUED
        assert len(mgr._ctx.injected) == 1

    def test_duplicate_after_refused_returns_refused(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        mgr.set_policy("refuse", session_id="sess-a")
        recipient = mgr._peers["sess-a"]
        e = _envelope(mgr, recipient.peer_id, "refused once")
        state = mgr._on_inbound(e)
        assert state == ReceiptState.REFUSED
        # Switch policy to accept; the duplicate must STILL return refused
        # (original persisted state), never re-evaluated.
        mgr.set_policy("accept", session_id="sess-a")
        state2 = mgr._on_inbound(e)
        assert state2 == ReceiptState.REFUSED
        assert mgr._ctx.injected == []


class TestConcurrentDuplicate:
    """REM-401/402: concurrent duplicates converge on one row, one host
    injection and one state."""

    def test_concurrent_duplicates_single_injection(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        recipient = mgr._peers["sess-a"]
        e = _envelope(mgr, recipient.peer_id, "concurrent dup")
        results: list[ReceiptState] = []
        lock = threading.Lock()

        def worker():
            state = mgr._on_inbound(e)
            with lock:
                results.append(state)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        # Exactly one row and one host injection; every result is the same
        # single state.
        row = mgr._store.get(e.message_id)
        assert row is not None
        assert len(mgr._ctx.injected) == 1, f"expected 1 inject, got {len(mgr._ctx.injected)}"
        assert len(set(r.value for r in results)) == 1


class TestReplyCorrelation:
    """REM-403: duplicate replies preserve original recipient/conversation/
    reply correlation and cannot leak across peers."""

    def test_duplicate_preserves_original_recipient(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        mgr.on_session_open("sess-b", platform="cli")
        rec_b = mgr._peers["sess-b"]
        e = _envelope(mgr, rec_b.peer_id, "to b only")
        mgr._on_inbound(e)
        row = mgr._store.get(e.message_id)
        assert row["recipient_peer_id"] == rec_b.peer_id
        # A duplicate must keep the same recipient, never switch to A.
        mgr._on_inbound(e)
        row2 = mgr._store.get(e.message_id)
        assert row2["recipient_peer_id"] == rec_b.peer_id
