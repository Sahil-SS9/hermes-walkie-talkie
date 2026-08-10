"""Last coverage-completing tests (REM-509): registry/transport/runtime
error branches that push line coverage over 90%."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.models import PeerRecord, ReceiptState
from agent_peer.paths import RuntimePaths


def _record(name: str = "p", **kw) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        status="idle",
        **kw,
    )


class TestRegistryErrorBranches:
    def test_update_presence_unknown_peer_noop(self, tmp_path):
        from agent_peer.models import Presence
        from agent_peer.registry import Registry

        reg = Registry(RuntimePaths(tmp_path / "runtime"))
        reg.update_presence(str(uuid.uuid4()), Presence.WORKING)  # must not raise

    def test_unregister_unknown_peer_returns_false(self, tmp_path):
        from agent_peer.registry import Registry

        reg = Registry(RuntimePaths(tmp_path / "runtime"))
        assert reg.unregister(str(uuid.uuid4())) is False

    def test_prune_no_handshake_removes_nothing(self, tmp_path):
        from agent_peer.registry import Registry

        reg = Registry(RuntimePaths(tmp_path / "runtime"))
        rec = _record(last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat())
        reg.register(rec)
        # No handshake callback -> prune removes nothing (fail safe).
        assert reg.prune() == []
        assert reg.get(rec.peer_id) is not None

    def test_prune_removes_stale_with_failed_handshake(self, tmp_path):
        from agent_peer.registry import Registry

        reg = Registry(RuntimePaths(tmp_path / "runtime"))
        rec = _record(last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat())
        import dataclasses

        rec = dataclasses.replace(rec, pid=2**31 - 1)
        reg.register(rec)
        removed = reg.prune(handshake_alive=lambda pid, instance: False)
        assert [r.peer_id for r in removed] == [rec.peer_id]


class TestTransportErrorBranches:
    def test_peer_credentials_fallback_without_sock(self):
        from agent_peer.transport import peer_credentials

        creds = peer_credentials(sock=None)
        assert creds["uid"] == os.geteuid()

    def test_client_connect_missing_socket(self, tmp_path):
        from agent_peer.errors import UnreachableError
        from agent_peer.models import PeerIdentity, make_envelope
        from agent_peer.transport import PeerClient

        env = make_envelope(
            sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="a", profile=""),
            recipient_peer_id=str(uuid.uuid4()),
            content="x",
        )
        client = PeerClient(str(tmp_path / "missing.sock"), connect_timeout=0.2)
        with pytest.raises(UnreachableError):
            client.request(env)


class TestRuntimeSendErrorBranches:
    def test_send_unreachable_no_registry(self, tmp_path):
        from agent_peer.models import PeerIdentity, make_envelope
        from agent_peer.runtime import PeerRuntimeManager

        mgr = PeerRuntimeManager(tmp_path / "runtime")
        try:
            env = make_envelope(
                sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="a", profile=""),
                recipient_peer_id=str(uuid.uuid4()),
                content="x",
            )
            receipt = mgr.send(env)
            assert receipt.state.value == "unreachable"
        finally:
            mgr.shutdown()

    def test_send_unreachable_no_socket(self, tmp_path):
        from agent_peer.models import PeerIdentity, make_envelope
        from agent_peer.runtime import PeerRuntimeManager

        mgr = PeerRuntimeManager(tmp_path / "runtime")
        try:
            rec = _record()
            mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            # Register a recipient with no socket path.
            from agent_peer.registry import Registry

            reg = Registry(mgr._paths)
            ghost = _record(socket_path="")
            reg.register(ghost)
            env = make_envelope(
                sender=PeerIdentity(peer_id=rec.peer_id, name="a", profile=""),
                recipient_peer_id=ghost.peer_id,
                content="x",
            )
            receipt = mgr.send(env)
            assert receipt.state.value == "unreachable"
        finally:
            mgr.shutdown()
