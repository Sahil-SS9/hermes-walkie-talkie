"""RED tests for exact listener ownership and ordered teardown (F-07, REM-404..407).

The plan §4.7 teardown order:

1. mark exact peer closing when its record still matches;
2. unregister exact listener FD from selector;
3. close exact listener FD;
4. close/unregister accepted connections belonging to that listener/peer;
5. compare socket UID/inode with the canonical record;
6. unlink exact owned socket;
7. remove exact matching registry record;
8. stop the supervisor only after the last peer is gone;
9. close wakeup pipe FDs and selector exactly once on final shutdown.

A path must never be unlinked while an untracked live listener remains bound
to it (NG-07).
"""

from __future__ import annotations

import os
import socket
import uuid
from pathlib import Path

import pytest

from agent_peer.models import PeerRecord, ReceiptState
from agent_peer.paths import RuntimePaths
from agent_peer.registry import Registry
from agent_peer.runtime import PeerRuntimeManager


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


def _fd_count() -> int:
    return len(os.listdir(f"/proc/{os.getpid()}/fd"))


class TestListenerTeardown:
    """REM-404: after unregister, connect to the old socket fails, selector
    lacks the listener, FD count returns to baseline and a path replacement
    cannot be unlinked."""

    def test_unregister_closes_listener_and_frees_fd(self, tmp_path):
        paths = RuntimePaths(tmp_path / "runtime")
        mgr = PeerRuntimeManager(paths)
        try:
            rec = _record("alpha")
            before = _fd_count()
            handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            assert _fd_count() >= before + 1  # listener fd open
            sock_path = handle.socket_path
            handle.close()
            # Connect must now fail.
            with pytest.raises(OSError):
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    s.connect(str(sock_path))
                finally:
                    s.close()
            # FD count returns to baseline (no leak).
            assert _fd_count() <= before + 1
        finally:
            mgr.shutdown()

    def test_selector_lacks_listener_after_unregister(self, tmp_path):
        paths = RuntimePaths(tmp_path / "runtime")
        mgr = PeerRuntimeManager(paths)
        try:
            rec = _record("beta")
            handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            # Before: the selector has the listener registered.
            listener_keys = [k for k in mgr._selector.get_map().values() if k.data == "listen"]
            assert len(listener_keys) == 1
            handle.close()
            listener_keys_after = [k for k in mgr._selector.get_map().values() if k.data == "listen"]
            assert listener_keys_after == []
        finally:
            mgr.shutdown()

    def test_registry_record_removed_on_unregister(self, tmp_path):
        paths = RuntimePaths(tmp_path / "runtime")
        reg = Registry(paths)
        mgr = PeerRuntimeManager(paths, registry=reg)
        try:
            rec = _record("gamma")
            handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            assert reg.get(rec.peer_id) is not None
            handle.close()
            assert reg.get(rec.peer_id) is None
            assert not Path(handle.socket_path).exists()
        finally:
            mgr.shutdown()

    def test_path_replacement_not_unlinked_by_teardown(self, tmp_path):
        """A replaced socket (new inode) must not be unlinked by a stale
        teardown (NG-07)."""
        paths = RuntimePaths(tmp_path / "runtime")
        mgr = PeerRuntimeManager(paths)
        try:
            rec = _record("delta")
            handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            sock_path = Path(handle.socket_path)
            # Replace the socket with a fresh bound listener at the same path.
            sock_path.unlink()
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            replacement.bind(str(sock_path))
            replacement.listen(1)
            replacement_ino = sock_path.stat().st_ino
            # Teardown of the ORIGINAL peer must not unlink the replacement.
            handle.close()
            assert sock_path.exists(), "replacement socket was wrongly unlinked"
            assert sock_path.stat().st_ino == replacement_ino
            replacement.close()
            sock_path.unlink()
        finally:
            mgr.shutdown()


class TestRepeatedLifecycleCleanliness:
    """REM-407: 100 register/unregister cycles leave zero live listeners,
    selector registrations, peer maps, registry records or socket files."""

    def test_100_cycles_leave_no_residue(self, tmp_path):
        paths = RuntimePaths(tmp_path / "runtime")
        mgr = PeerRuntimeManager(paths)
        try:
            for i in range(100):
                rec = _record(f"cycle-{i % 5}")
                handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
                handle.close()
            # No listeners, no selector registrations, no peer maps.
            listener_keys = [k for k in mgr._selector.get_map().values() if k.data == "listen"]
            assert listener_keys == []
            conn_keys = [k for k in mgr._selector.get_map().values() if k.data == "conn"]
            assert conn_keys == []
            assert mgr._peers == {}
            assert mgr._connections == {}
            # No registry records or socket files beyond the dirs themselves.
            assert list(paths.registry_dir.glob("*.json")) == []
            assert list(paths.sockets_dir.glob("*.sock")) == []
        finally:
            mgr.shutdown()

    def test_supervisor_stops_after_last_peer(self, tmp_path):
        paths = RuntimePaths(tmp_path / "runtime")
        mgr = PeerRuntimeManager(paths)
        try:
            rec = _record("last")
            handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            assert mgr._thread is not None and mgr._thread.is_alive()
            handle.close()
            # After the last peer is gone, the supervisor thread stops.
            mgr._join_thread()
            assert mgr._thread is None or not mgr._thread.is_alive()
        finally:
            mgr.shutdown()
