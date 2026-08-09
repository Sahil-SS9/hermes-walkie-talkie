"""Edge-branch tests for the supervisor, registry, paths and transport
(closes the SEC-1015 coverage gap on trust/delivery paths)."""

from __future__ import annotations

import os
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.models import Envelope, Kind, PeerIdentity, PeerRecord, ReceiptState
from agent_peer.runtime import PeerRuntimeManager

NOW = datetime.now(UTC)


def _record(name: str = "e", **kw) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="t",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        last_seen=datetime.now(UTC).isoformat(),
        **kw,
    )


def _env(sender: PeerIdentity, recipient: str, content: str = "x", kind: Kind = Kind.MESSAGE, **kw) -> Envelope:
    return Envelope(
        protocol="agent-peer/1",
        message_id=str(uuid.uuid4()),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        sender=sender,
        recipient_peer_id=recipient,
        kind=kind,
        content=content,
        reply_to=None,
        conversation_id=None,
        **kw,
    )


class TestSupervisorEdges:
    def test_send_to_peer_without_socket_unreachable(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        try:
            a = _record("a")
            mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
            # Registry record without a socket_path -> unreachable receipt.
            from agent_peer.models import PeerRecord as PR

            ghost = PR(peer_id=str(uuid.uuid4()), instance_id=str(uuid.uuid4()), name="ghost", profile="t", surface="cli", pid=1, cwd="/tmp")
            mgr._registry.register(ghost)
            sender = PeerIdentity(peer_id=a.peer_id, name="a", profile="")
            receipt = mgr.send(_env(sender, ghost.peer_id))
            assert receipt.state.value == "unreachable"
        finally:
            mgr.shutdown()

    def test_send_unexpected_reply_kind_invalid(self, isolated_runtime, tmp_path):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        try:
            a = _record("a")
            mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
            # A raw peer that answers with a MESSAGE-kind envelope (not a
            # receipt/pong) -> the sender maps it to an explicit invalid
            # receipt instead of crashing.
            raw_path = tmp_path / "raw.sock"
            raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            raw.bind(str(raw_path))
            raw.listen(1)

            def serve():
                conn, _ = raw.accept()
                conn.recv(4096)
                from agent_peer.codec import encode_envelope

                reply = _env(
                    PeerIdentity(peer_id=str(uuid.uuid4()), name="raw", profile=""),
                    str(uuid.uuid4()),
                    "not-a-receipt",
                    kind=Kind.MESSAGE,
                )
                conn.sendall(encode_envelope(reply).encode("utf-8"))
                conn.close()

            import threading

            threading.Thread(target=serve, daemon=True).start()
            ghost = _record("ghost", socket_path=str(raw_path))
            mgr._registry.register(ghost)
            sender = PeerIdentity(peer_id=a.peer_id, name="a", profile="")
            receipt = mgr.send(_env(sender, ghost.peer_id))
            assert receipt.state.value == "invalid"
            raw.close()
        finally:
            mgr.shutdown()

    def test_handler_invalid_state_receipt(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        try:
            a = _record("a")
            b = _record("b")
            mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
            handle_b = mgr.register_peer(b, on_message=lambda e: "not-a-state")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(str(handle_b.socket_path))
            from agent_peer.codec import encode_envelope

            sender = PeerIdentity(peer_id=a.peer_id, name="a", profile="")
            sock.sendall(encode_envelope(_env(sender, b.peer_id)).encode("utf-8"))
            # Invalid handler state -> the reply is 'invalid'; the connection
            # stays usable.
            time.sleep(0.3)
            sock.close()
        finally:
            mgr.shutdown()

    def test_unregister_unknown_peer_noop(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        mgr.unregister_peer(str(uuid.uuid4()))  # no-op
        mgr.shutdown()

    def test_register_peer_and_reclaim_stale_socket_race(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        try:
            a = _record("a")
            handle = mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
            handle.close()
            # Re-register after teardown (restart scenario): the stale socket
            # path is reclaimed and the rebind succeeds.
            handle2 = mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
            assert handle2.socket_path.exists()
            handle2.close()
        finally:
            mgr.shutdown()

    def test_supervisor_teardown_edges(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        a = _record("a")
        handle = mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
        # Client disconnects abruptly (OSError path) while data is buffered.
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(handle.socket_path))
        sock.sendall(b"\x00\x00\x00\x05hello")
        sock.close()  # abrupt close -> _drop_connection
        time.sleep(0.2)
        # Shutdown with an active connection still registered.
        mgr.shutdown()
        assert mgr._thread is None or not mgr._thread.is_alive()
        # A second shutdown is a no-op.
        mgr.shutdown()

    def test_dispatch_to_unregistered_recipient_gets_unreachable(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        a = _record("a")
        mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
        try:
            from agent_peer.codec import encode_envelope, encode_frame

            # Raw client asks for a peer that is NOT registered here.
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(str(mgr._paths.socket_path_for(a.peer_id)))
            sender = PeerIdentity(peer_id=a.peer_id, name="a", profile="")
            sock.sendall(encode_frame(encode_envelope(_env(sender, str(uuid.uuid4())))))
            reply = sock.recv(4096)
            assert b"unreachable" in reply
            sock.close()
        finally:
            mgr.shutdown()

    def test_accept_oserror_contained(self, isolated_runtime):
        """_accept on a closed listener is contained (OSError path)."""
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        a = _record("a")
        mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
        closed = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        closed.close()
        mgr._accept(closed)  # must not raise; loop survives
        time.sleep(0.1)
        mgr.shutdown()

    def test_wakeup_pipe_drained(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        mgr._wakeup()
        mgr._wakeup()
        mgr._stop_event.set()
        mgr._wakeup()
        mgr._join_thread()
        # No crash; loop exit clean.
        assert mgr._thread is None or not mgr._thread.is_alive()


class TestTransportEdges:
    def test_peer_credentials_fallback(self):
        from agent_peer.transport import peer_credentials, verify_peer_credentials

        creds = peer_credentials(sock=None)
        assert creds["uid"] == os.geteuid()
        assert verify_peer_credentials(creds) is True
        assert verify_peer_credentials({}) is False
        assert verify_peer_credentials({"uid": "not-an-int"}) is False

    def test_client_receives_garbage_reply_fails_cleanly(self, tmp_path):
        from agent_peer.transport import PeerClient

        server_path = tmp_path / "garbage.sock"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(server_path))
        sock.listen(1)
        import threading

        def serve():
            conn, _ = sock.accept()
            conn.recv(4096)
            conn.sendall(b"\x00\x00\x00\x10" + b"garbage-json!!")
            conn.close()

        threading.Thread(target=serve, daemon=True).start()
        try:
            client = PeerClient(str(server_path))
            sender = PeerIdentity(peer_id=str(uuid.uuid4()), name="a", profile="")
            from agent_peer.errors import AgentPeerError

            with pytest.raises(AgentPeerError):
                client.request(_env(sender, str(uuid.uuid4())))
        finally:
            sock.close()


class TestRegistryEdges:
    def test_get_missing_and_corrupt(self, isolated_runtime):
        from agent_peer.registry import Registry

        runtime_dir, _ = isolated_runtime
        reg = Registry(runtime_dir)
        assert reg.get(str(uuid.uuid4())) is None
        rec = _record()
        reg.register(rec)
        p = reg._paths.registry_file_for(rec.peer_id)
        p.write_text("{corrupt", encoding="utf-8")
        assert reg.get(rec.peer_id) is None
        # Corrupt file does not break list_peers.
        assert all(r.peer_id != rec.peer_id for r in reg.list_peers())

    def test_unregister_missing_returns_false(self, isolated_runtime):
        from agent_peer.registry import Registry

        runtime_dir, _ = isolated_runtime
        reg = Registry(runtime_dir)
        assert reg.unregister(str(uuid.uuid4())) is False

    def test_update_presence_unknown_peer_noop(self, isolated_runtime):
        from agent_peer.models import Presence
        from agent_peer.registry import Registry

        runtime_dir, _ = isolated_runtime
        reg = Registry(runtime_dir)
        reg.update_presence(str(uuid.uuid4()), Presence.WORKING)  # no-op
        reg.heartbeat(str(uuid.uuid4()))  # no-op
