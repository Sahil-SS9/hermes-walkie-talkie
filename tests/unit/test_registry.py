"""RED tests for the owner-local peer registry (AP-404..AP-411)."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_peer.models import PeerRecord, Presence
from agent_peer.registry import Registry


def _record(peer_id: str | None = None, instance_id: str | None = None, name: str = "peer", **kw) -> PeerRecord:
    return PeerRecord(
        peer_id=peer_id or str(uuid.uuid4()),
        instance_id=instance_id or str(uuid.uuid4()),
        name=name,
        profile=kw.pop("profile", "default"),
        surface=kw.pop("surface", "cli"),
        pid=kw.pop("pid", os.getpid()),
        cwd=kw.pop("cwd", "/tmp"),
        last_seen=kw.pop("last_seen", ""),
        **kw,
    )


@pytest.fixture
def registry_dir(tmp_path) -> Path:
    d = tmp_path / "runtime"
    d.mkdir(mode=0o700)
    return d


class TestRegistryAtomicWrites:
    def test_register_writes_owner_only_file(self, registry_dir):
        reg = Registry(registry_dir)
        rec = _record()
        reg.register(rec)
        f = registry_dir / "registry" / f"{rec.peer_id}.json"
        assert f.exists()
        assert (f.stat().st_mode & 0o077) == 0

    def test_register_updates_atomically(self, registry_dir):
        reg = Registry(registry_dir)
        rec = _record(name="first")
        reg.register(rec)
        updated = _record(peer_id=rec.peer_id, instance_id=rec.instance_id, name="second")
        reg.register(updated)
        peers = reg.list_peers()
        assert len(peers) == 1
        assert peers[0].name == "second"

    def test_windows_registry_read_ignores_posix_mode_bits(self, registry_dir, monkeypatch):
        """Windows ownership is enforced by the DACL, not POSIX mode bits."""
        reg = Registry(registry_dir)
        rec = _record()
        reg.register(rec)
        record_file = registry_dir / "registry" / f"{rec.peer_id}.json"
        record_file.chmod(0o666)

        # Simulate Windows after setup: ``same_owner`` already bypasses UID
        # checks there, so this isolates the registry's stale POSIX-mode gate.
        monkeypatch.setattr("agent_peer.registry.os.name", "nt")

        found = reg.get(rec.peer_id)
        assert found is not None
        assert found.peer_id == rec.peer_id
        assert found.instance_id == rec.instance_id

    def test_unregister_removes_only_own_file(self, registry_dir):
        reg = Registry(registry_dir)
        a, b = _record(), _record()
        reg.register(a)
        reg.register(b)
        reg.unregister(a.peer_id)
        peers = reg.list_peers()
        assert [p.peer_id for p in peers] == [b.peer_id]

    def test_corrupt_file_never_breaks_discovery(self, registry_dir):
        reg = Registry(registry_dir)
        reg.register(_record())
        (registry_dir / "registry" / "corrupt.json").write_text("{not json")
        peers = reg.list_peers()
        assert len(peers) == 1  # corrupt entry skipped, not fatal


class TestPresence:
    def test_update_presence(self, registry_dir):
        reg = Registry(registry_dir)
        rec = _record()
        reg.register(rec)
        reg.update_presence(rec.peer_id, Presence.WORKING)
        peers = reg.list_peers()
        assert peers[0].status == Presence.WORKING.value

    def test_heartbeat_updates_last_seen(self, registry_dir):
        reg = Registry(registry_dir)
        rec = _record(last_seen="")
        reg.register(rec)
        time.sleep(0.01)
        reg.heartbeat(rec.peer_id)
        peers = reg.list_peers()
        assert peers[0].last_seen

    def test_unknown_peer_heartbeat_is_noop(self, registry_dir):
        reg = Registry(registry_dir)
        reg.heartbeat(str(uuid.uuid4()))  # must not raise


class TestReachabilityAndStale:
    def test_fresh_peer_reported(self, registry_dir):
        reg = Registry(registry_dir)
        rec = _record()
        reg.register(rec)
        assert reg.is_fresh(rec.peer_id)

    def test_old_timestamp_marked_stale_candidate(self, registry_dir):
        reg = Registry(registry_dir)
        rec = _record(last_seen=(datetime.now(UTC) - timedelta(minutes=10)).isoformat())
        reg.register(rec)
        assert not reg.is_fresh(rec.peer_id)

    def test_stale_live_pid_never_pruned(self, registry_dir):
        """AP-408: removal requires expiry PLUS failed handshake; PID-liveness
        alone must never trigger file deletion."""
        reg = Registry(registry_dir)
        rec = _record(last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat())
        reg.register(rec)
        removed = reg.prune(now=datetime.now(UTC), handshake_alive=lambda pid, instance: True)
        assert removed == []
        assert reg.list_peers()  # file still present

    def test_dead_pid_pruned_when_handshake_fails(self, registry_dir):
        reg = Registry(registry_dir)
        rec = _record(pid=2**31 - 1, last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat())
        reg.register(rec)
        removed = reg.prune(now=datetime.now(UTC), handshake_alive=lambda pid, instance: False)
        assert [r.peer_id for r in removed] == [rec.peer_id]
        assert reg.list_peers() == []

    def test_pid_reuse_requires_instance_match(self, registry_dir):
        """AP-407: a live PID never proves identity without instance match."""
        reg = Registry(registry_dir)
        rec = _record(pid=os.getpid())
        reg.register(rec)
        # The registry must expose the instance so callers can verify it;
        # a mismatched instance must not be treated as the same peer.
        found = reg.get(rec.peer_id)
        assert found.instance_id == rec.instance_id


class TestCollisionsAndCrossProfile:
    def test_duplicate_names_remain_distinct(self, registry_dir):
        reg = Registry(registry_dir)
        a = _record(name="dupe")
        b = _record(name="dupe")
        reg.register(a)
        reg.register(b)
        peers = reg.list_peers()
        assert len(peers) == 2
        names = [p.name for p in peers]
        assert names == ["dupe", "dupe"]
        # Exact peer_id lookup is the deterministic tiebreaker.
        assert reg.get(a.peer_id).peer_id == a.peer_id
        assert reg.get(b.peer_id).peer_id == b.peer_id

    def test_cross_profile_discovery_shared_root(self, registry_dir):
        """AP-410: separate homes under the same UID share the registry."""
        reg_a = Registry(registry_dir)
        reg_b = Registry(registry_dir)
        a = _record(profile="prof-a")
        b = _record(profile="prof-b")
        reg_a.register(a)
        reg_b.register(b)
        seen_by_a = reg_a.list_peers()
        assert {p.profile for p in seen_by_a} == {"prof-a", "prof-b"}

    def test_concurrent_alias_updates_always_parseable(self, registry_dir):
        """AP-411: simultaneous name changes leave a parseable atomic record."""
        reg = Registry(registry_dir)
        rec = _record(name="original")
        reg.register(rec)
        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def worker(i: int) -> None:
            try:
                barrier.wait(timeout=5)
                reg.register(_record(peer_id=rec.peer_id, instance_id=rec.instance_id, name=f"name-{i}"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors
        peers = reg.list_peers()
        assert len(peers) == 1
        assert peers[0].name in {f"name-{i}" for i in range(8)}
