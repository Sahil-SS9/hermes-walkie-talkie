"""RED tests for canonical identity, alias preservation and multi-session
isolation (R2, F-02/F-03, REM-201..REM-208, REM-214).

These tests pin the F-03 defect: every tool/command/inbox/policy/send/
reset/finalise path must use the INVOKING exact session, never
``next(iter(...))`` or process-global first-peer selection. They also pin
F-02: alias updates must preserve the canonical bound socket/instance record
and never republish the pre-bind blank record.
"""

from __future__ import annotations

import pytest

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


@pytest.fixture
def two_sessions(env):
    mgr = get_manager()
    mgr.on_session_start("sess-a", platform="cli")
    mgr.on_session_start("sess-b", platform="cli")
    return mgr


class TestCanonicalBoundRecord:
    """REM-201: after register_peer, the session manager's stored record
    must contain the actual bound socket path, UID and inode."""

    def test_stored_record_has_bound_socket_authority(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        rec = mgr._peers["sess-a"]
        assert rec.socket_path, "stored record must have a bound socket path"
        assert rec.socket_uid != 0, "stored record must capture socket UID"
        assert rec.socket_inode != 0, "stored record must capture socket inode"
        assert rec.protocol == "agent-peer/1"

    def test_registry_record_is_the_bound_record(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        rec = mgr._peers["sess-a"]
        reg_rec = mgr._registry.get(rec.peer_id)
        assert reg_rec.socket_path == rec.socket_path
        assert reg_rec.socket_inode == rec.socket_inode
        assert reg_rec.socket_uid == rec.socket_uid


class TestAliasPreservation:
    """REM-202/F-02: rename and clear alias while live; socket path/UID/
    inode, peer ID, instance ID, session ID and reachability unchanged."""

    def test_rename_preserves_bound_authority(self, two_sessions):
        mgr = two_sessions
        rec_b = mgr._peers["sess-b"]
        before = (rec_b.peer_id, rec_b.instance_id, rec_b.session_id, rec_b.socket_path, rec_b.socket_uid, rec_b.socket_inode)
        mgr.set_alias_for(rec_b.peer_id, "newname")
        rec_b2 = mgr._peers["sess-b"]
        after = (rec_b2.peer_id, rec_b2.instance_id, rec_b2.session_id, rec_b2.socket_path, rec_b2.socket_uid, rec_b2.socket_inode)
        assert before == after, "alias rename must preserve bound authority"
        assert rec_b2.name == "newname"

    def test_alias_preserves_reachability(self, two_sessions):
        mgr = two_sessions
        rec_b = mgr._peers["sess-b"]
        mgr.set_alias_for(rec_b.peer_id, "backend")
        # The peer must still be reachable through discovery with full authority.
        from agent_peer.discovery import DiscoveryService

        svc = DiscoveryService(mgr._paths, registry=mgr._registry)
        record, err = svc.resolve_peer("backend")
        assert err is None, err
        assert record is not None
        assert record.socket_path == rec_b.socket_path
        assert record.peer_id == rec_b.peer_id

    def test_set_alias_exact_session(self, two_sessions):
        """set_alias must target the exact session, not the first peer."""
        mgr = two_sessions
        # Make session A's name distinct; set_alias("x", session_id="sess-a")
        # must rename A, never silently pick B.
        mgr.set_alias_for(mgr._peers["sess-a"].peer_id, "orig-a")
        mgr.set_alias_for(mgr._peers["sess-b"].peer_id, "orig-b")
        mgr.set_alias("renamed-a", session_id="sess-a")
        assert mgr._peers["sess-a"].name == "renamed-a"
        assert mgr._peers["sess-b"].name == "orig-b"


class TestExactSender:
    """REM-206: with two local sessions, a tool call from session B must
    identify B as sender, not the first registered peer."""

    def test_make_envelope_from_exact_session(self, two_sessions):
        mgr = two_sessions
        rec_a = mgr._peers["sess-a"]
        rec_b = mgr._peers["sess-b"]
        env = mgr._make_envelope(session_id="sess-b", recipient=rec_a.peer_id, content="from b")
        assert env.sender.peer_id == rec_b.peer_id
        assert env.sender.name == rec_b.name


class TestExactInboxAndPolicy:
    """REM-207: reading/releasing/refusing or changing policy in session A
    cannot observe or mutate B's state."""

    def _held_for(self, mgr, session_id: str, content: str):
        """Insert a held row for the exact session's peer."""
        from agent_peer.models import ReceiptState

        rec = mgr._peers[session_id]
        env = mgr._make_envelope(session_id=session_id, recipient=rec.peer_id, content=content)
        mgr._store.record(
            {
                "message_id": env.message_id,
                "recipient_peer_id": env.recipient_peer_id,
                "sender_peer_id": env.sender.peer_id,
                "kind": env.kind.value,
                "content": env.content,
                "state": ReceiptState.HELD.value,
                "created_at": env.created_at.isoformat(),
                "expires_at": env.expires_at.isoformat(),
                "reply_to": env.reply_to,
                "conversation_id": env.conversation_id,
                "delivered_at": None,
                "hop_count": env.hop_count,
            }
        )
        return env.message_id

    def test_read_inbox_scoped_to_exact_session(self, two_sessions):
        mgr = two_sessions
        held_b = self._held_for(mgr, "sess-b", "for b only")
        # Reading A's inbox must NOT include B's held message.
        inbox_a = mgr.read_inbox(session_id="sess-a")
        assert all(row["message_id"] != held_b for row in inbox_a)
        inbox_b = mgr.read_inbox(session_id="sess-b")
        assert any(row["message_id"] == held_b for row in inbox_b)

    def test_release_scoped_to_exact_session(self, two_sessions):
        mgr = two_sessions
        held_b = self._held_for(mgr, "sess-b", "release b")
        # Releasing from A's perspective must NOT release B's message.
        assert mgr.release_message(held_b, session_id="sess-a") is False
        assert mgr.release_message(held_b, session_id="sess-b") is True

    def test_policy_scoped_to_exact_session(self, two_sessions):
        mgr = two_sessions
        # Policy is session-scoped: changing A's policy must not change B's.
        mgr.set_policy("refuse", session_id="sess-a")
        assert mgr.policy_for("sess-a") == "refuse"
        assert mgr.policy_for("sess-b") == "accept"


class TestExactResetFinalize:
    """REM-208: resetting/finalising A leaves B's listener, record, policy,
    alias and inbox intact."""

    def test_finalize_a_leaves_b_intact(self, two_sessions):
        mgr = two_sessions
        rec_b = mgr._peers["sess-b"]
        mgr.on_session_finalize("sess-a", platform="cli", reason="test")
        assert "sess-a" not in mgr._peers
        assert "sess-b" in mgr._peers
        assert mgr._peers["sess-b"].peer_id == rec_b.peer_id
        # B's socket is still live.
        assert mgr._registry.get(rec_b.peer_id) is not None

    def test_reset_a_leaves_b_unaffected(self, two_sessions):
        mgr = two_sessions
        rec_b = mgr._peers["sess-b"]
        mgr.on_session_reset("sess-a2", platform="cli", old_session_id="sess-a")
        assert "sess-a" not in mgr._peers
        assert "sess-a2" in mgr._peers
        assert mgr._peers["sess-b"].peer_id == rec_b.peer_id


class TestMultiSessionConcurrency:
    """REM-214: two sessions in one process operate concurrently without
    sender, inbox, policy, alias, reset or finalise leakage."""

    def test_concurrent_operations_isolated(self, two_sessions):
        import threading

        mgr = two_sessions
        errors: list[Exception] = []

        def worker(session_id: str):
            try:
                for i in range(20):
                    mgr.set_alias(f"name-{session_id}-{i}", session_id=session_id)
                    mgr.set_policy("accept", session_id=session_id)
                    inbox = mgr.read_inbox(session_id=session_id)
                    assert isinstance(inbox, list)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(s,)) for s in ("sess-a", "sess-b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors
        # Both sessions still exist and are distinct.
        assert set(mgr._peers.keys()) == {"sess-a", "sess-b"}
        assert mgr._peers["sess-a"].peer_id != mgr._peers["sess-b"].peer_id


class TestExactTurnLifecycle:
    """F-09/REM-304/305/308: open A/B, work A, idle A, reset A->A2,
    finalise B — each event affects only its exact peer."""

    def test_open_then_turn_lifecycle_is_exact(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        mgr.on_session_open("sess-b", platform="cli")
        # Registration exists before any turn (idle).
        assert mgr._peers["sess-a"].status == "idle"
        assert mgr._peers["sess-b"].status == "idle"
        # Turn start marks only A working.
        mgr.on_session_start("sess-a", platform="cli")
        assert mgr._peers["sess-a"].status == "working"
        assert mgr._peers["sess-b"].status == "idle"
        # Turn end marks A idle, B untouched.
        mgr.on_session_end("sess-a", platform="cli")
        assert mgr._peers["sess-a"].status == "idle"
        assert mgr._peers["sess-b"].status == "idle"

    def test_reset_rotates_only_old_session(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        mgr.on_session_open("sess-b", platform="cli")
        rec_b = mgr._peers["sess-b"]
        mgr.on_session_reset("sess-a2", platform="cli", old_session_id="sess-a")
        assert "sess-a" not in mgr._peers
        assert "sess-a2" in mgr._peers
        assert mgr._peers["sess-b"].peer_id == rec_b.peer_id
        assert mgr._peers["sess-b"].status == "idle"

    def test_finalise_only_exact_session(self, env):
        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        mgr.on_session_open("sess-b", platform="cli")
        rec_b = mgr._peers["sess-b"]
        mgr.on_session_finalize("sess-a", platform="cli", reason="close")
        assert "sess-a" not in mgr._peers
        assert mgr._peers["sess-b"].peer_id == rec_b.peer_id
