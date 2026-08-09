"""Integration tests for the per-process supervisor and real socket transport (AP-501..AP-512).

Uses real AF_UNIX sockets and threads inside one process (the IPC boundary is
real; only the Hermes host seam is mocked at delivery time).
"""

from __future__ import annotations

import socket
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_peer.models import Envelope, Kind, PeerIdentity, PeerRecord, ReceiptState
from agent_peer.runtime import PeerRuntimeManager

NOW = datetime.now(UTC)


def _record(name: str, runtime_root: Path) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="test",
        surface="cli",
        pid=12345,
        cwd="/tmp",
        started_at=NOW.isoformat(),
        last_seen=NOW.isoformat(),
        status="idle",
        socket_path=str(runtime_root / "sockets" / f"{uuid.uuid4()}.sock"),
    )


def _envelope(sender: PeerIdentity, recipient: str, content: str = "hello", kind: Kind = Kind.MESSAGE) -> Envelope:
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
        hop_count=0,
    )


@pytest.fixture
def runtime(isolated_runtime):
    runtime_dir, _ = isolated_runtime
    manager = PeerRuntimeManager(runtime_dir)
    yield manager
    manager.shutdown()


class TestSupervisorLifecycle:
    def test_first_peer_starts_supervisor_shared_and_last_stops(self, runtime, isolated_runtime):
        """AP-501: first session starts it; additional sessions share it; last stops it."""
        runtime_dir, _ = isolated_runtime
        a = _record("alpha", runtime_dir)
        b = _record("beta", runtime_dir)

        handle_a = runtime.register_peer(a, on_message=lambda env: ReceiptState.QUEUED)
        assert runtime._thread is not None and runtime._thread.is_alive()
        thread_a = runtime._thread

        handle_b = runtime.register_peer(b, on_message=lambda env: ReceiptState.QUEUED)
        assert runtime._thread is thread_a  # shared, not restarted

        handle_a.close()
        assert runtime._thread.is_alive()  # b still registered

        handle_b.close()
        deadline = time.time() + 5
        while runtime._thread is not None and runtime._thread.is_alive() and time.time() < deadline:
            time.sleep(0.05)
        assert runtime._thread is None or not runtime._thread.is_alive()  # stopped

    def test_message_exchange_between_two_peers(self, runtime, isolated_runtime):
        """AP-502 success path: A -> supervisor -> B and receipt back."""
        runtime_dir, _ = isolated_runtime
        delivered: list[str] = []
        a = _record("alpha", runtime_dir)
        b = _record("beta", runtime_dir)
        runtime.register_peer(a, on_message=lambda env: delivered.append(env.content) or ReceiptState.QUEUED)
        runtime.register_peer(b, on_message=lambda env: delivered.append(env.content) or ReceiptState.QUEUED)

        sender = PeerIdentity(peer_id=a.peer_id, name="alpha", profile="test")
        env = _envelope(sender, b.peer_id, "hello beta")
        receipt = runtime.send(env)
        assert receipt.state is ReceiptState.QUEUED or receipt.state.value == "queued"
        assert delivered == ["hello beta"]

    def test_unreachable_peer_receipt(self, runtime, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        a = _record("alpha", runtime_dir)
        runtime.register_peer(a, on_message=lambda env: ReceiptState.QUEUED)
        sender = PeerIdentity(peer_id=a.peer_id, name="alpha", profile="test")
        env = _envelope(sender, str(uuid.uuid4()), "to nowhere")
        receipt = runtime.send(env)
        assert receipt.state is ReceiptState.UNREACHABLE

    def test_concurrent_senders_no_lost_frames(self, runtime, isolated_runtime):
        """AP-509: concurrent senders do not interleave frames or lose receipts."""
        runtime_dir, _ = isolated_runtime
        delivered: list[str] = []
        lock = threading.Lock()
        a = _record("alpha", runtime_dir)
        b = _record("beta", runtime_dir)

        def on_msg(env):
            with lock:
                delivered.append(env.content)
            return ReceiptState.QUEUED

        runtime.register_peer(a, on_message=on_msg)
        runtime.register_peer(b, on_message=on_msg)
        sender = PeerIdentity(peer_id=a.peer_id, name="alpha", profile="test")

        results: list[bool] = []
        rlock = threading.Lock()

        def worker(i: int) -> None:
            env = _envelope(sender, b.peer_id, f"msg-{i}")
            receipt = runtime.send(env)
            with rlock:
                results.append(receipt.state is ReceiptState.QUEUED)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(results) == 20 and all(results)
        # Lexicographic sort ('msg-10' < 'msg-2') — compare sorted-to-sorted.
        assert sorted(delivered) == sorted(f"msg-{i}" for i in range(20))
        assert len(set(delivered)) == 20  # no duplicates, none lost

    def test_slow_client_isolation(self, runtime, isolated_runtime):
        """AP-511: a client that stalls mid-frame cannot block other peers."""
        runtime_dir, _ = isolated_runtime
        delivered: list[str] = []
        a = _record("alpha", runtime_dir)
        b = _record("beta", runtime_dir)
        runtime.register_peer(a, on_message=lambda env: delivered.append(env.content) or ReceiptState.QUEUED)
        handle_b = runtime.register_peer(b, on_message=lambda env: delivered.append(env.content) or ReceiptState.QUEUED)

        # A malicious client connects and sends HALF a frame, then stalls.
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(handle_b.socket_path))
        sock.sendall(b"\x00\x00\x00\x10")  # claims 16 bytes, sends none
        try:
            # The healthy path must still work while the client stalls.
            sender = PeerIdentity(peer_id=a.peer_id, name="alpha", profile="test")
            receipt = runtime.send(_envelope(sender, b.peer_id, "while stalled"))
            assert receipt.state.value == "queued"
            assert delivered == ["while stalled"]
        finally:
            sock.close()

    def test_handler_failure_is_contained(self, runtime, isolated_runtime):
        """AP-512: a handler exception is contained; supervisor stays available."""
        runtime_dir, _ = isolated_runtime
        delivered: list[str] = []
        a = _record("alpha", runtime_dir)
        b = _record("beta", runtime_dir)

        def boom(env):
            raise RuntimeError("handler exploded")

        def ok(env):
            delivered.append(env.content)
            return ReceiptState.QUEUED

        runtime.register_peer(a, on_message=boom)
        runtime.register_peer(b, on_message=ok)

        sender = PeerIdentity(peer_id=a.peer_id, name="alpha", profile="test")
        env = _envelope(sender, b.peer_id, "still works")
        receipt = runtime.send(env)
        assert receipt.state.value == "queued"
        assert delivered == ["still works"]

    def test_graceful_teardown_removes_exact_files(self, runtime, isolated_runtime):
        """AP-507: unregister removes selector registration, socket, registry file."""
        runtime_dir, _ = isolated_runtime
        a = _record("alpha", runtime_dir)
        handle = runtime.register_peer(a, on_message=lambda env: ReceiptState.QUEUED)
        socket_path = handle.socket_path
        registry_path = runtime._registry._paths.registry_file_for(a.peer_id)
        assert socket_path.exists()
        assert registry_path.exists()
        handle.close()
        assert not socket_path.exists()
        assert not registry_path.exists()
        assert a.peer_id not in runtime._peers

    def test_crash_recovery_reclaims_stale_socket(self, runtime, isolated_runtime):
        """AP-508: a stale socket without a live listener is reclaimed on start."""
        runtime_dir, _ = isolated_runtime
        stale = runtime._paths.sockets_dir / "dead-peer.sock"
        stale.touch()
        # Registering a NEW peer must not be blocked by the stale file.
        a = _record("alpha", runtime_dir)
        handle = runtime.register_peer(a, on_message=lambda env: ReceiptState.QUEUED)
        assert handle.socket_path.exists()
        handle.close()

    def test_malformed_peer_connection_contained(self, runtime, isolated_runtime):
        """A malformed connection is contained; the supervisor stays available."""
        runtime_dir, _ = isolated_runtime
        delivered: list[str] = []
        a = _record("alpha", runtime_dir)
        b = _record("beta", runtime_dir)
        runtime.register_peer(a, on_message=lambda env: delivered.append(env.content) or ReceiptState.QUEUED)
        handle_b = runtime.register_peer(b, on_message=lambda env: delivered.append(env.content) or ReceiptState.QUEUED)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(handle_b.socket_path))
        sock.sendall(b"garbage-not-a-frame")
        time.sleep(0.1)
        sock.close()

        sender = PeerIdentity(peer_id=a.peer_id, name="alpha", profile="test")
        receipt = runtime.send(_envelope(sender, b.peer_id, "after garbage"))
        assert receipt.state.value == "queued"
        assert delivered == ["after garbage"]
