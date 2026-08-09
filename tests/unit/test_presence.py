"""Tests for PresenceManager (closes the SEC-1015 coverage gap)."""

from __future__ import annotations

import time
import uuid

from agent_peer.models import PeerRecord, Presence
from agent_peer.presence import PresenceManager, stale_after
from agent_peer.registry import Registry


def _record() -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name="p",
        profile="t",
        surface="cli",
        pid=1,
        cwd="/tmp",
    )


def test_initial_state_idle(isolated_runtime):
    runtime_dir, _ = isolated_runtime
    reg = Registry(runtime_dir)
    rec = _record()
    reg.register(rec)
    pm = PresenceManager(reg, rec.peer_id)
    assert pm.status is Presence.IDLE


def test_status_transitions_write(isolated_runtime):
    runtime_dir, _ = isolated_runtime
    reg = Registry(runtime_dir)
    rec = _record()
    reg.register(rec)
    pm = PresenceManager(reg, rec.peer_id)
    pm.mark_working()
    assert pm.status is Presence.WORKING
    assert reg.get(rec.peer_id).status == Presence.WORKING.value
    pm.mark_idle()
    assert reg.get(rec.peer_id).status == Presence.IDLE.value
    pm.mark_closing()
    assert reg.get(rec.peer_id).status == Presence.CLOSING.value


def test_repeat_status_no_write(isolated_runtime):
    runtime_dir, _ = isolated_runtime
    reg = Registry(runtime_dir)
    rec = _record()
    reg.register(rec)
    pm = PresenceManager(reg, rec.peer_id)
    pm.mark_idle()  # already idle -> no registry write
    assert reg.get(rec.peer_id).status == Presence.IDLE.value


def test_heartbeat_bounded_by_interval(isolated_runtime):
    runtime_dir, _ = isolated_runtime
    reg = Registry(runtime_dir)
    rec = _record()
    reg.register(rec)
    pm = PresenceManager(reg, rec.peer_id, interval=60.0)
    assert pm.heartbeat() is True  # first write allowed
    assert pm.heartbeat() is False  # within interval -> skipped
    assert pm.heartbeat(force=True) is True


def test_heartbeat_updates_last_seen(isolated_runtime):
    runtime_dir, _ = isolated_runtime
    reg = Registry(runtime_dir)
    rec = _record()
    reg.register(rec)
    before = reg.get(rec.peer_id).last_seen
    time.sleep(0.01)
    pm = PresenceManager(reg, rec.peer_id, interval=0.0)
    pm.heartbeat()
    assert reg.get(rec.peer_id).last_seen != before


def test_stale_after_constant():
    assert stale_after() == 45.0
