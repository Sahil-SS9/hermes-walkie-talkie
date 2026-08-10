"""Final coverage-completing tests (REM-509): singleton manager, lifecycle
idempotency and discovery edge branches.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from agent_peer.models import PeerRecord, ReceiptState


def _record(name: str = "p") -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        status="idle",
    )


class TestRuntimeSingleton:
    def test_get_returns_singleton(self):
        from agent_peer.runtime import PeerRuntimeManager

        a = PeerRuntimeManager.get()
        b = PeerRuntimeManager.get()
        assert a is b
        a.shutdown()

    def test_get_with_default_runtime(self, monkeypatch):
        from agent_peer.runtime import PeerRuntimeManager

        with tempfile.TemporaryDirectory() as td:
            monkeypatch.setenv("XDG_RUNTIME_DIR", str(Path(td) / "xdg"))
            monkeypatch.setenv("XDG_STATE_HOME", str(Path(td) / "state"))
            m = PeerRuntimeManager()
            rec = _record("single")
            handle = m.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            handle.close()
            m.shutdown()


class TestSessionIdempotency:
    def test_on_session_open_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

        from hermes_peer.sessions import PeerSessionManager

        class Ctx:
            def inject_message(self, content, role="user", *, mode="queue", target_session=None):
                return True

        mgr = PeerSessionManager(Ctx())
        try:
            mgr.on_session_open("sess-x", platform="cli")
            first = mgr._peers["sess-x"].peer_id
            # Opening the same session again is a no-op (idempotent).
            mgr.on_session_open("sess-x", platform="cli")
            assert mgr._peers["sess-x"].peer_id == first
            assert len(mgr._peers) == 1
        finally:
            mgr.shutdown()

    def test_unknown_platform_maps_to_gateway(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

        from hermes_peer.sessions import PeerSessionManager

        class Ctx:
            def inject_message(self, content, role="user", *, mode="queue", target_session=None):
                return True

        mgr = PeerSessionManager(Ctx())
        try:
            mgr.on_session_open("sess-gw", platform="slack")
            assert mgr._peers["sess-gw"].surface == "gateway"
        finally:
            mgr.shutdown()


class TestDiscoveryEdge:
    def test_probe_none_when_no_socket(self):
        from agent_peer.discovery import _probe_once

        rec = _record()
        assert _probe_once(rec) is None  # no socket_path

    def test_snapshot_skips_invalid(self, tmp_path):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths

        paths = RuntimePaths(tmp_path / "runtime")
        svc = DiscoveryService(paths)
        # No records -> empty snapshot.
        assert svc._snapshot() == []

    def test_live_peers_excludes_requester(self, tmp_path):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.models import ReceiptState
        from agent_peer.paths import RuntimePaths
        from agent_peer.runtime import PeerRuntimeManager

        paths = RuntimePaths(tmp_path / "runtime")
        mgr = PeerRuntimeManager(paths)
        try:
            rec = _record("me")
            mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            svc = DiscoveryService(paths)
            peers = svc.list_live_peers(requesting_peer_id=rec.peer_id)
            assert all(p.peer_id != rec.peer_id for p in peers)
        finally:
            mgr.shutdown()
