"""Coverage-completing tests for agent_peer.discovery (REM-509).

Targets the discovery paths not yet exercised by the cross-process tests:
repair_stale fence refusals (instance/socket/inode changes, live-listener
guard), resolve_peer resolution orders (session_id, name~shortID, bare-name
collisions), and _parse_record containment/validation rejections.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_peer.models import PeerRecord
from agent_peer.paths import RuntimePaths
from agent_peer.registry import Registry


def _record(**kw) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        session_id=kw.pop("session_id", f"sess-{uuid.uuid4().hex[:6]}"),
        name=kw.pop("name", "peer"),
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        status="idle",
        **kw,
    )


@pytest.fixture
def runtime_dir(tmp_path) -> Path:
    d = tmp_path / "runtime"
    d.mkdir(mode=0o700)
    return d


class TestResolvePeerOrders:
    def test_exact_uuid_without_live_record_returns_error(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService

        missing = str(uuid.uuid4())
        found, err = DiscoveryService(RuntimePaths(runtime_dir)).resolve_peer(missing)

        assert found is None
        assert err == {"error": f"no live peer with peer_id {missing!r}"}

    def test_resolve_by_exact_session_id(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService

        # A live peer is required for session resolution; use a real manager.
        from agent_peer.models import ReceiptState
        from agent_peer.runtime import PeerRuntimeManager

        paths = RuntimePaths(runtime_dir)
        mgr = PeerRuntimeManager(paths)
        try:
            rec = _record(session_id="sess-exact", name="by-session")
            mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            svc = DiscoveryService(paths)
            found, err = svc.resolve_peer("sess-exact")
            assert err is None and found is not None
            assert found.session_id == "sess-exact"
        finally:
            mgr.shutdown()

    def test_resolve_by_name_tilde_short_id(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.models import ReceiptState
        from agent_peer.runtime import PeerRuntimeManager

        paths = RuntimePaths(runtime_dir)
        mgr = PeerRuntimeManager(paths)
        try:
            rec = _record(name="unique-name")
            mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
            svc = DiscoveryService(paths)
            target = f"unique-name~{rec.peer_id[:8]}"
            found, err = svc.resolve_peer(target)
            assert err is None and found is not None
            assert found.peer_id == rec.peer_id
        finally:
            mgr.shutdown()

    def test_resolve_bare_name_collision_returns_candidates(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService
        from agent_peer.models import ReceiptState
        from agent_peer.runtime import PeerRuntimeManager

        paths = RuntimePaths(runtime_dir)
        mgr = PeerRuntimeManager(paths)
        try:
            a = _record(name="dupe")
            b = _record(name="dupe")
            mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
            mgr.register_peer(b, on_message=lambda e: ReceiptState.QUEUED)
            svc = DiscoveryService(paths)
            found, err = svc.resolve_peer("dupe")
            assert found is None
            assert err is not None and "ambigu" in err["error"].lower()
            assert len(err["candidates"]) == 2
        finally:
            mgr.shutdown()

    def test_resolve_unknown_returns_error(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService

        svc = DiscoveryService(RuntimePaths(runtime_dir))
        found, err = svc.resolve_peer("nobody")
        assert found is None and err is not None


class TestRepairFences:
    def _make_live_peer(self, runtime_dir):
        from agent_peer.models import ReceiptState
        from agent_peer.runtime import PeerRuntimeManager

        paths = RuntimePaths(runtime_dir)
        mgr = PeerRuntimeManager(paths)
        rec = _record()
        handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
        # Return the CANONICAL BOUND record (socket_path populated).
        return mgr, handle, (handle.record or rec)

    def test_repair_refuses_instance_changed(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService

        mgr, handle, rec = self._make_live_peer(runtime_dir)
        try:
            paths = RuntimePaths(runtime_dir)
            reg = Registry(paths)
            # Overwrite the record with a different instance but the SAME
            # real bound socket path: the instance probe fails, yet the
            # socket is live, so cleanup must refuse.
            import dataclasses

            forged = dataclasses.replace(rec, instance_id=str(uuid.uuid4()))
            reg.register(forged)
            svc = DiscoveryService(paths)
            removed = svc.repair_stale(runtime_dir)
            assert removed == []
            # The record still exists (cleanup refused).
            assert reg.get(rec.peer_id) is not None
        finally:
            mgr.shutdown()

    def test_repair_refuses_live_listener_socket(self, runtime_dir):
        """A stale record pointing at a LIVE bound socket must not be
        cleaned (NG-07 live-listener guard)."""
        from agent_peer.discovery import DiscoveryService

        mgr, handle, rec = self._make_live_peer(runtime_dir)
        try:
            paths = RuntimePaths(runtime_dir)
            reg = Registry(paths)
            import dataclasses

            # Mark the record stale (old heartbeat) but keep the real socket.
            stale = dataclasses.replace(
                rec, last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat()
            )
            reg.register(stale)
            svc = DiscoveryService(paths)
            removed = svc.repair_stale(runtime_dir)
            assert removed == []
            assert reg.get(rec.peer_id) is not None
        finally:
            mgr.shutdown()

    def test_repair_keeps_fresh_live_peer(self, runtime_dir):
        from agent_peer.discovery import DiscoveryService

        mgr, _handle, record = self._make_live_peer(runtime_dir)
        try:
            removed = DiscoveryService(RuntimePaths(runtime_dir)).repair_stale(runtime_dir)

            assert removed == []
            assert Registry(RuntimePaths(runtime_dir)).get(record.peer_id) is not None
        finally:
            mgr.shutdown()

    def test_repair_removes_dead_socket_record(self, runtime_dir):
        """A record with a missing socket and old heartbeat IS cleaned."""
        from agent_peer.discovery import DiscoveryService

        paths = RuntimePaths(runtime_dir)
        reg = Registry(paths)
        dead = _record(
            socket_uid=os.geteuid(),
            socket_inode=0,
            last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        )
        import dataclasses

        dead = dataclasses.replace(
            dead,
            socket_path=str(paths.socket_path_for(dead.peer_id, dead.instance_id)),
        )
        reg.register(dead)
        svc = DiscoveryService(paths)
        removed = svc.repair_stale(runtime_dir)
        assert [r.peer_id for r in removed] == [dead.peer_id]
        assert reg.get(dead.peer_id) is None


class TestParseRecordRejections:
    def test_non_json_path_is_not_a_registry_record(self, runtime_dir):
        from agent_peer.discovery import _parse_record

        paths = RuntimePaths(runtime_dir)
        path = paths.registry_dir / "not-a-record.txt"
        path.write_text("ignored", encoding="utf-8")
        assert _parse_record(path, paths) is None

    def test_regular_file_cannot_stand_in_for_bound_socket(self, runtime_dir):
        import dataclasses

        from agent_peer.discovery import _parse_record

        paths = RuntimePaths(runtime_dir)
        registry = Registry(paths)
        record = _record()
        socket_path = paths.socket_path_for(record.peer_id, record.instance_id)
        socket_path.write_text("not a socket", encoding="utf-8")
        socket_path.chmod(0o600)
        socket_stat = socket_path.stat()
        bound = dataclasses.replace(
            record,
            socket_path=str(socket_path),
            socket_uid=socket_stat.st_uid,
            socket_inode=socket_stat.st_ino,
        )
        registry.register(bound)
        assert _parse_record(paths.registry_file_for(bound.peer_id), paths) is None

    def test_filename_peer_id_mismatch_rejected(self, runtime_dir):
        from agent_peer.discovery import _parse_record

        paths = RuntimePaths(runtime_dir)
        rec = _record()
        # Write under a DIFFERENT filename than the embedded peer_id.
        wrong = paths.registry_dir / f"{uuid.uuid4()}.json"
        wrong.write_text(
            json.dumps(
                {
                    "peer_id": rec.peer_id,
                    "instance_id": rec.instance_id,
                    "name": rec.name,
                    "status": "idle",
                }
            ),
            encoding="utf-8",
        )
        assert _parse_record(wrong, paths) is None

    def test_socket_outside_runtime_root_rejected(self, runtime_dir, tmp_path):
        from agent_peer.discovery import _parse_record

        paths = RuntimePaths(runtime_dir)
        rec = _record(socket_path=str(tmp_path / "evil" / "x.sock"))
        good = paths.registry_dir / f"{rec.peer_id}.json"
        good.write_text(
            json.dumps(
                {
                    "peer_id": rec.peer_id,
                    "instance_id": rec.instance_id,
                    "name": rec.name,
                    "status": "idle",
                    "socket_path": str(tmp_path / "evil" / "x.sock"),
                }
            ),
            encoding="utf-8",
        )
        assert _parse_record(good, paths) is None

    def test_corrupt_json_rejected(self, runtime_dir):
        from agent_peer.discovery import _parse_record

        paths = RuntimePaths(runtime_dir)
        bad = paths.registry_dir / f"{uuid.uuid4()}.json"
        bad.write_text("{not json", encoding="utf-8")
        assert _parse_record(bad, paths) is None


class TestCoverageGuardBranches:
    def test_empty_timestamps_fail_closed(self):
        from agent_peer.discovery import _parse_iso as parse_discovery_iso
        from agent_peer.registry import _parse_iso as parse_registry_iso

        assert parse_discovery_iso("") is None
        assert parse_registry_iso("") is None

    def test_fenced_metadata_update_can_preserve_heartbeat(self, runtime_dir):
        registry = Registry(RuntimePaths(runtime_dir))
        registry.register(_record(name="before"))
        current = registry.list_peers()[0]

        updated = registry.update_if_current(
            current.peer_id,
            expected_instance_id=current.instance_id,
            expected_socket_path=current.socket_path,
            expected_socket_uid=current.socket_uid,
            expected_socket_inode=current.socket_inode,
            name="after",
            touch_last_seen=False,
        )

        assert updated is not None
        assert updated.name == "after"
        assert updated.last_seen == current.last_seen

    def test_missing_and_malformed_heartbeats_are_not_fresh(self, runtime_dir):
        registry = Registry(RuntimePaths(runtime_dir))
        assert registry.is_fresh(str(uuid.uuid4())) is False

        malformed = _record(last_seen="not-an-rfc3339-timestamp")
        registry.register(malformed)
        assert registry.is_fresh(malformed.peer_id) is False
