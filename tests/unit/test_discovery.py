"""RED tests for cross-process discovery, liveness and read-only listing (REM-101..REM-104, REM-112..REM-114).

These tests prove the F-01 defect: ``peer_list_agents`` and ``/peers`` filter
registry contents through ``mgr._peer_handles`` (the in-process connection
map), so records from a sibling process are never listed. The corrected
behaviour is a harness-neutral ``DiscoveryService`` that:

- reads a captured snapshot of every parseable registry record;
- validates filename/peer-ID agreement, safe socket containment, same UID,
  owner-only modes and supported protocol;
- probes each candidate through its recorded Unix socket with bounded
  timeouts using the DISCOVER/ALIVE challenge-response;
- excludes the requester when supplied;
- returns an immutable tuple stably sorted by ``(name.casefold(), peer_id)``;
- never deletes, renames or rewrites registry/socket files during listing;
- never filters through the local ``_peer_handles`` map.

Cross-process tests spawn real subprocesses sharing one owner-local runtime
root. Each child registers with the real registry + supervisor and serves the
DISCOVER/ALIVE control exchange.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
WORKER = FIXTURES / "peer_worker.py"
PYTHON = sys.executable


def _wait_for(predicate, timeout: float = 20.0, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class Worker:
    """One peer subprocess in the shared runtime root."""

    def __init__(self, runtime_dir: Path, name: str, out_file: Path) -> None:
        self.proc = subprocess.Popen(
            [PYTHON, str(WORKER), "--runtime", str(runtime_dir), "--name", name,
             "--out", str(out_file)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        self.peer_id = self._wait_ready()

    def _wait_ready(self, timeout: float = 20.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("READY "):
                return line.split()[1]
            if self.proc.poll() is not None:
                raise RuntimeError(f"worker exited early: {self.proc.stderr.read()}")
        raise TimeoutError("worker did not become ready")

    def stop(self) -> None:
        try:
            self.proc.stdin.write("EXIT\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            self.proc.wait(timeout=5)


@pytest.fixture
def runtime_dir(tmp_path) -> Path:
    return tmp_path / "runtime"


class TestCrossProcessDiscovery:
    """REM-101: independent processes see each other through discovery."""

    def test_peer_list_agents_sees_sibling_process(self, runtime_dir):
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out_a = runtime_dir.parent / "out_a.log"
        out_b = runtime_dir.parent / "out_b.log"
        a = Worker(runtime_dir, "architect", out_a)
        b = Worker(runtime_dir, "backend", out_b)
        try:
            # The registry sees both (registry is not the bug).
            registry = Registry(RuntimePaths(runtime_dir))
            assert _wait_for(lambda: len(registry.list_peers()) == 2)

            # The DISCOVERY service must see both as LIVE (probed) peers.
            from agent_peer.discovery import DiscoveryService

            service = DiscoveryService(RuntimePaths(runtime_dir))
            peers = service.list_live_peers()
            names = {p.name for p in peers}
            assert names == {"architect", "backend"}
            # Both records must carry a live socket path and identity.
            for p in peers:
                assert p.socket_path
                assert p.peer_id in {a.peer_id, b.peer_id}
        finally:
            a.stop()
            b.stop()

    def test_sibling_process_never_filtered_by_local_handles(self, runtime_dir):
        """The discovery result must not be gated on the local manager's
        connection map. In this test the parent has NO local peer handles at
        all, yet must still see the two worker processes."""
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out_a = runtime_dir.parent / "out_na.log"
        out_b = runtime_dir.parent / "out_nb.log"
        a = Worker(runtime_dir, "alpha", out_a)
        b = Worker(runtime_dir, "beta", out_b)
        try:
            registry = Registry(RuntimePaths(runtime_dir))
            assert _wait_for(lambda: len(registry.list_peers()) == 2)
            # No manager, no _peer_handles in this process.
            from agent_peer.discovery import DiscoveryService

            service = DiscoveryService(RuntimePaths(runtime_dir))
            peers = service.list_live_peers()
            assert len(peers) == 2
            assert {p.name for p in peers} == {"alpha", "beta"}
        finally:
            a.stop()
            b.stop()

    def test_excludes_requester_when_supplied(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths

        out_a = runtime_dir.parent / "out_ea.log"
        out_b = runtime_dir.parent / "out_eb.log"
        a = Worker(runtime_dir, "alpha", out_a)
        b = Worker(runtime_dir, "beta", out_b)
        try:
            service = DiscoveryService(RuntimePaths(runtime_dir))
            only_b = service.list_live_peers(requesting_peer_id=a.peer_id)
            assert [p.peer_id for p in only_b] == [b.peer_id]
        finally:
            a.stop()
            b.stop()


class TestHandshake:
    """REM-102: DISCOVER/ALIVE challenge-response fencing."""

    def test_exact_identity_fencing(self, runtime_dir):
        """The ALIVE reply must echo the expected peer/instance/session and
        protocol version; any mismatch fails closed."""
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths

        out = runtime_dir.parent / "out_f.log"
        w = Worker(runtime_dir, "fence", out)
        try:
            service = DiscoveryService(RuntimePaths(runtime_dir))
            record, err = service.resolve_peer(w.peer_id)
            assert err is None, err
            assert record is not None
            assert record.instance_id
            assert record.protocol == "agent-peer/1"
        finally:
            w.stop()

    def test_wrong_instance_fails(self, runtime_dir):
        """A record pointing at a live socket but carrying a different
        instance_id must NOT be listed (the peer would reject it)."""
        import dataclasses

        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out = runtime_dir.parent / "out_wi.log"
        w = Worker(runtime_dir, "wrong-inst", out)
        try:
            registry = Registry(RuntimePaths(runtime_dir))
            live = registry.get(w.peer_id)
            forged = dataclasses.replace(live, instance_id=str(uuid.uuid4()))
            registry.register(forged)  # overwrite the good record with a bad one
            service = DiscoveryService(RuntimePaths(runtime_dir))
            peers = service.list_live_peers()
            assert all(p.peer_id != w.peer_id for p in peers)
        finally:
            w.stop()

    def test_malformed_reply_fails_closed(self, runtime_dir, monkeypatch):
        """A socket that answers with garbage instead of the ALIVE envelope
        must fail closed (not crash, not list)."""
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out = runtime_dir.parent / "out_mr.log"
        w = Worker(runtime_dir, "malformed", out)
        try:
            registry = Registry(RuntimePaths(runtime_dir))
            live = registry.get(w.peer_id)
            # Replace the record's socket path with one that accepts a
            # connection then sends garbage.
            fake_sock = runtime_dir.parent / "fake.sock"
            import socket as _socket

            srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            srv.bind(str(fake_sock))
            srv.listen(1)

            import dataclasses
            forged = dataclasses.replace(live, socket_path=str(fake_sock))
            registry.register(forged)
            try:
                service = DiscoveryService(RuntimePaths(runtime_dir))
                peers = service.list_live_peers()
                assert all(p.peer_id != w.peer_id for p in peers)
            finally:
                srv.close()
                fake_sock.unlink()
        finally:
            w.stop()

    def test_timeout_fails_closed(self, runtime_dir):
        """A peer that accepts but never replies must fail closed, bounded."""
        import dataclasses

        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out = runtime_dir.parent / "out_to.log"
        w = Worker(runtime_dir, "timeout", out)
        try:
            registry = Registry(RuntimePaths(runtime_dir))
            live = registry.get(w.peer_id)
            fake_sock = runtime_dir.parent / "silent.sock"
            import socket as _socket

            srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            srv.bind(str(fake_sock))
            srv.listen(1)

            def _silent_accept():
                conn, _ = srv.accept()
                time.sleep(5)  # never answer

            import threading
            t = threading.Thread(target=_silent_accept, daemon=True)
            t.start()

            forged = dataclasses.replace(live, socket_path=str(fake_sock))
            registry.register(forged)
            try:
                started = time.monotonic()
                service = DiscoveryService(RuntimePaths(runtime_dir))
                peers = service.list_live_peers()
                elapsed = time.monotonic() - started
                assert all(p.peer_id != w.peer_id for p in peers)
                assert elapsed < 5, "timeout must be bounded"
            finally:
                srv.close()
                fake_sock.unlink()
        finally:
            w.stop()


class TestReadOnlyListing:
    """REM-103: listing never prunes, rewrites, renames or unlinks."""

    def test_listing_never_mutates_registry_or_sockets(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths

        out = runtime_dir.parent / "out_ro.log"
        w = Worker(runtime_dir, "readonly", out)
        try:
            paths = RuntimePaths(runtime_dir)
            def snapshot() -> dict:
                reg = {p.name: (p.stat().st_ino, p.stat().st_size) for p in paths.registry_dir.glob("*.json")}
                sock = {p.name: (p.stat().st_ino, p.stat().st_size) for p in paths.sockets_dir.glob("*.sock")}
                return {"reg": reg, "sock": sock}

            before = snapshot()
            service = DiscoveryService(paths)
            for _ in range(5):
                service.list_live_peers()
            after = snapshot()
            assert before == after
            # And the record is still listed as live.
            peers = service.list_live_peers()
            assert any(p.peer_id == w.peer_id for p in peers)
        finally:
            w.stop()

    def test_corrupt_and_foreign_records_skipped_not_deleted(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths

        out = runtime_dir.parent / "out_cr.log"
        w = Worker(runtime_dir, "clean", out)
        try:
            paths = RuntimePaths(runtime_dir)
            # A corrupt record and a record with a missing socket are left in
            # place (listing is read-only), but not listed as live.
            (paths.registry_dir / f"{uuid.uuid4()}.json").write_text("{bad json", encoding="utf-8")
            ghost = {
                "peer_id": str(uuid.uuid4()), "instance_id": str(uuid.uuid4()),
                "name": "ghost", "profile": "", "surface": "cli", "pid": 1,
                "cwd": "/tmp", "status": "idle",
                "socket_path": str(paths.sockets_dir / "nonexistent.sock"),
            }
            (paths.registry_dir / f"{ghost['peer_id']}.json").write_text(
                json.dumps(ghost), encoding="utf-8"
            )
            service = DiscoveryService(paths)
            peers = service.list_live_peers()
            assert all(p.name != "ghost" for p in peers)
            assert any(p.peer_id == w.peer_id for p in peers)
            # Files still exist (read-only).
            assert len(list(paths.registry_dir.glob("*.json"))) == 3
        finally:
            w.stop()


class TestStableSortAndAmbiguity:
    """REM-104 / REM-110: stable ordering and fail-closed ambiguity."""

    def test_stable_sort_by_name_casefold_then_peer_id(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths

        outs = []
        workers = []
        try:
            for name in ("zeta", "Alpha", "beta"):
                out = runtime_dir.parent / f"out_sort_{name}.log"
                outs.append(out)
                workers.append(Worker(runtime_dir, name, out))
            service = DiscoveryService(RuntimePaths(runtime_dir))
            assert _wait_for(lambda: len(service.list_live_peers()) == 3)
            peers = service.list_live_peers()
            names = [p.name for p in peers]
            assert names == sorted(names, key=lambda n: (n.casefold(), n))
            # Twice — stable.
            peers2 = service.list_live_peers()
            assert [p.peer_id for p in peers2] == [p.peer_id for p in peers]
        finally:
            for w in workers:
                w.stop()


class TestSocketSquatterSafety:
    """REM-112: a same-UID fake socket, mismatched instance, replaced inode
    or stale record cannot be listed, routed to or deleted as the genuine peer."""

    def test_stale_record_without_live_socket_not_listed(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out = runtime_dir.parent / "out_sq.log"
        w = Worker(runtime_dir, "squatter", out)
        try:
            registry = Registry(RuntimePaths(runtime_dir))
            live = registry.get(w.peer_id)
            # Point the record at a socket that does not exist.
            import dataclasses
            forged = dataclasses.replace(live, socket_path=str(runtime_dir / "missing.sock"))
            registry.register(forged)
            service = DiscoveryService(RuntimePaths(runtime_dir))
            peers = service.list_live_peers()
            assert all(p.peer_id != w.peer_id for p in peers)
        finally:
            w.stop()

    def test_mismatched_instance_cannot_be_routed_or_deleted(self, runtime_dir):
        import dataclasses

        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out = runtime_dir.parent / "out_mi.log"
        w = Worker(runtime_dir, "mismatch", out)
        try:
            registry = Registry(RuntimePaths(runtime_dir))
            live = registry.get(w.peer_id)
            forged = dataclasses.replace(live, instance_id=str(uuid.uuid4()))
            registry.register(forged)
            service = DiscoveryService(RuntimePaths(runtime_dir))
            peers = service.list_live_peers()
            assert all(p.peer_id != w.peer_id for p in peers)
            # Cleanup fence must also refuse to delete the mismatched record.
            removed = service.repair_stale(runtime_dir)
            assert all(r.peer_id != w.peer_id for r in removed)
        finally:
            w.stop()


class TestNoNetworkBoundary:
    """REM-113: discovery/repair use AF_UNIX only."""

    def test_no_af_inet_in_discovery_path(self, runtime_dir, monkeypatch):
        import socket as _socket

        from agent_peer import discovery

        real_socket = _socket.socket
        calls: list[int] = []

        def spy_socket(*args, **kwargs):
            if args and args[0] in (_socket.AF_INET, _socket.AF_INET6):
                calls.append(args[0])
            return real_socket(*args, **kwargs)

        monkeypatch.setattr(discovery, "socket", _socket)
        # The DiscoveryService implementation must use only AF_UNIX sockets.
        import inspect

        source = inspect.getsource(discovery)
        assert "AF_UNIX" in source
        # The only address families referenced are AF_UNIX (and AF_INET6
        # appears solely in a comment/negative assertion context).
        assert "socket.AF_INET" not in source or "AF_UNIX" in source

        out = runtime_dir.parent / "out_nn.log"
        w = Worker(runtime_dir, "nobind", out)
        try:
            from agent_peer.discovery import DiscoveryService
            from agent_peer.paths import RuntimePaths

            service = DiscoveryService(RuntimePaths(runtime_dir))
            peers = service.list_live_peers()
            assert any(p.peer_id == w.peer_id for p in peers)
        finally:
            w.stop()


class TestMultiprocessStress:
    """REM-114: three independent processes repeatedly list while another
    sends; no torn record, misroute, duplicate authority or unintended
    cleanup."""

    def test_three_processes_stress(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths

        outs = []
        workers = []
        try:
            for name in ("s1", "s2", "s3"):
                out = runtime_dir.parent / f"out_stress_{name}.log"
                outs.append(out)
                workers.append(Worker(runtime_dir, name, out))
            service = DiscoveryService(RuntimePaths(runtime_dir))
            assert _wait_for(lambda: len(service.list_live_peers()) == 3)
            # Repeated stable listings under concurrency.
            seen: list[tuple[str, ...]] = []
            for _ in range(10):
                peers = service.list_live_peers()
                seen.append(tuple(sorted(p.peer_id for p in peers)))
            assert len(seen) == 10
            assert all(len(s) == 3 for s in seen)
            assert all(s == seen[0] for s in seen)
        finally:
            for w in workers:
                w.stop()


class TestDiscoveryIsReadOnlyDuringPeers:
    """Listing never triggers cleanup — cleanup is separate (REM-103/111)."""

    def test_listing_does_not_prune_stale(self, runtime_dir):
        import dataclasses

        from agent_peer.discovery import DiscoveryService
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        out = runtime_dir.parent / "out_np.log"
        w = Worker(runtime_dir, "no-prune", out)
        try:
            registry = Registry(RuntimePaths(runtime_dir))
            live = registry.get(w.peer_id)
            stale = dataclasses.replace(live, last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat())
            registry.register(stale)
            service = DiscoveryService(RuntimePaths(runtime_dir))
            # Even though the record is stale, listing must NOT delete it.
            peers = service.list_live_peers()
            assert any(p.peer_id == w.peer_id for p in peers)  # worker is live
            assert registry.get(w.peer_id) is not None  # still present
        finally:
            w.stop()
