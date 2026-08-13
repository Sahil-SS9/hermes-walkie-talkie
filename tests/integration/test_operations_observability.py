"""Manager-level metrics/events/doctor integration (P6, G1.1..G1.8)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_peer.sessions import PeerSessionManager


class _Ctx:
    def __init__(self, home: Path) -> None:
        self.hermes_home = str(home)
        self.injected: list[tuple] = []

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        self.injected.append((content, role, mode, target_session))
        return True

    def register_hook(self, *a, **k):
        pass

    def register_command(self, *a, **k):
        pass

    def register_tool(self, *a, **k):
        pass


@pytest.fixture()
def mgr(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    os.chmod(runtime_dir, 0o700)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    os.chmod(state_dir, 0o700)
    monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(state_dir))
    home = tmp_path / "home"
    home.mkdir()
    m = PeerSessionManager(_Ctx(home), runtime_root=runtime_dir)
    try:
        m.on_session_open("s1", platform="cli")
        yield m
    finally:
        m.shutdown()


def test_metrics_record_delivery_through_manager(mgr):
    """A real inbound delivery increments the content-free metrics."""
    # The manager's own peer receives a message from a second manager.
    import uuid as _uuid

    from agent_peer.models import Kind, PeerIdentity, make_envelope

    me = mgr._peers["s1"]
    other = str(_uuid.uuid4())
    env = make_envelope(
        sender=PeerIdentity(peer_id=other, name="other", profile=""),
        recipient_peer_id=me.peer_id,
        kind=Kind.MESSAGE,
        content="hello",
    )
    mgr._on_inbound(env)
    snap = mgr.metrics_snapshot()
    assert snap["delivered"] == 1
    assert snap["failed"] == 0


def test_metrics_hold_refuse_recorded(mgr):
    from agent_peer.models import Kind, PeerIdentity, make_envelope

    me = mgr._peers["s1"]
    other = "22222222-2222-4222-8222-222222222222"
    mgr.set_policy("refuse", session_id="s1")
    env = make_envelope(
        sender=PeerIdentity(peer_id=other, name="other", profile=""),
        recipient_peer_id=me.peer_id,
        kind=Kind.MESSAGE,
        content="nope",
    )
    mgr._on_inbound(env)
    snap = mgr.metrics_snapshot()
    assert snap["failed"] == 1
    assert snap["failure_reasons"]["refused"] == 1


def test_event_broker_subscribe_drain(mgr):
    sid = mgr.subscribe_events()
    from agent_peer.models import Kind, PeerIdentity, make_envelope

    me = mgr._peers["s1"]
    env = make_envelope(
        sender=PeerIdentity(peer_id="33333333-3333-4333-8333-333333333333", name="x", profile=""),
        recipient_peer_id=me.peer_id,
        kind=Kind.MESSAGE,
        content="event-test",
    )
    mgr._on_inbound(env)
    events = mgr.drain_events(sid)
    assert any(e["kind"] == "message" for e in events)
    mgr.unsubscribe_events(sid)


def test_doctor_has_health_snapshot_and_metrics(mgr):
    d = mgr.doctor()
    assert d["backend"] == "posix"
    assert d["local_sessions"] == 1
    assert isinstance(d["metrics"], dict)
    assert isinstance(d["problems"], list)
    assert "stale_count" in d
    assert "groups" in d
    assert "active_requests" in d
