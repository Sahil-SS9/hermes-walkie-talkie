"""PeerSessionManager lifecycle edge branches (P11.1 coverage).

Covers the legacy-host and no-op paths: start-without-open, end/reset
without registration, rotation without handle/alias, finalize no-op,
presence on missing record, multi-session reset without old id.
"""

from __future__ import annotations

import pytest

from agent_peer.models import Presence
from hermes_peer.sessions import PeerSessionManager


@pytest.fixture()
def mgr(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)

    class Ctx:
        pass

    return PeerSessionManager(ctx=Ctx(), runtime_root=tmp_path / "runtime")


class TestSessionLifecycleEdges:
    def test_start_without_open_registers_legacy(self, mgr):
        mgr.on_session_start("legacy-sess", platform="cli")
        assert "legacy-sess" in mgr._session_to_peer
        assert mgr._peers["legacy-sess"].status == Presence.WORKING.value

    def test_presence_missing_record_noop(self, mgr):
        # _set_presence on an unknown session must return without error.
        mgr._set_presence("unknown", Presence.WORKING)

    def test_end_without_open_noop(self, mgr):
        mgr.on_session_end("unknown-sess", platform="cli")  # no exception

    def test_reset_without_old_id_single_session(self, mgr):
        mgr.on_session_start("only-sess", platform="cli")
        mgr.on_session_reset("next-sess", platform="cli")
        assert "only-sess" not in mgr._session_to_peer
        assert "next-sess" in mgr._session_to_peer

    def test_reset_without_old_id_multi_session_raises(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        with pytest.raises(ValueError, match="old_session_id"):
            mgr.on_session_reset("sess-c", platform="cli")

    def test_finalize_unknown_session_noop(self, mgr):
        mgr.on_session_finalize("unknown-sess", platform="cli")  # no exception

    def test_finalize_closes_handle_and_cleans(self, mgr):
        mgr.on_session_start("sess-x", platform="cli")
        peer_id = mgr._session_to_peer["sess-x"]
        mgr.on_session_finalize("sess-x", platform="cli", reason="shutdown")
        assert "sess-x" not in mgr._session_to_peer
        assert peer_id not in mgr._peer_handles
        assert peer_id not in mgr._peers

    def test_rotate_without_old_record(self, mgr):
        # Rotation of a session that has a peer entry but no handle.
        mgr.on_session_start("old-sess", platform="cli")
        old_id = mgr._session_to_peer["old-sess"]
        # Simulate a host that already closed the handle.
        mgr._peer_handles.pop(old_id, None)
        mgr.on_session_reset("new-sess", platform="cli", old_session_id="old-sess")
        assert "new-sess" in mgr._session_to_peer


class TestHeartbeatPump:
    """X1: the bounded background heartbeat pump keeps last_seen fresh."""

    def test_ensure_presence_creates_manager(self, mgr):
        mgr.on_session_start("hb-sess", platform="cli")
        peer_id = mgr._session_to_peer["hb-sess"]
        # _presence is keyed by session_id -> PresenceManager (X1).
        assert "hb-sess" in mgr._presence
        assert mgr._presence["hb-sess"]._peer_id == peer_id

    def test_heartbeat_thread_runs_and_is_daemon(self, mgr):
        assert mgr._heartbeat_thread is not None
        assert mgr._heartbeat_thread.daemon is True
        assert mgr._heartbeat_thread.name == "hermes-peer-heartbeat"

    def test_heartbeat_touches_last_seen(self, mgr):
        mgr.on_session_start("hb-sess", platform="cli")
        peer_id = mgr._session_to_peer["hb-sess"]
        before = mgr._registry.get(peer_id).last_seen
        # Force a write (bypass the interval throttle) and confirm the
        # registry record's last_seen advances.
        assert mgr._presence["hb-sess"].heartbeat(force=True) is True
        after = mgr._registry.get(peer_id).last_seen
        assert after is not None and after >= before

    def test_drop_presence_on_finalize(self, mgr):
        mgr.on_session_start("hb-sess", platform="cli")
        mgr.on_session_finalize("hb-sess", reason="test")
        assert "hb-sess" not in mgr._presence

    def test_shutdown_stops_heartbeat_thread(self, mgr):
        mgr.on_session_start("hb-sess", platform="cli")
        mgr.shutdown()
        assert mgr._heartbeat_thread is None
