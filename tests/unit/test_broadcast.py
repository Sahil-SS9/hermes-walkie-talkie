"""Broadcast engine unit tests (P4.4..P4.9, G3.5..G3.10)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

import pytest

from agent_peer.broadcast import BroadcastEngine, deterministic_child_id
from agent_peer.errors import ValidationError
from agent_peer.groups import GroupStore
from agent_peer.store import MessageStore


class _FakeRecord:
    def __init__(self, peer_id: str) -> None:
        self.peer_id = peer_id


@dataclass
class Env:
    engine: BroadcastEngine
    store: MessageStore
    groups: GroupStore
    sent: list
    live: dict


@pytest.fixture()
def env(tmp_path):
    store = MessageStore(tmp_path / "messages.sqlite3")
    groups = GroupStore(store)
    sent: list[dict] = []
    live: dict[str, _FakeRecord] = {}

    def send(agent, peer, content, *, child_message_id=None):
        sent.append({"agent": agent, "peer": peer, "content": content, "child": child_message_id})
        return {"state": "queued", "detail": ""}

    def resolve(agent_id, pin=None):
        return live.get(agent_id)

    eng = BroadcastEngine(
        store, groups, send=send, resolve=resolve, concurrency=4, max_retries=1
    )
    yield Env(engine=eng, store=store, groups=groups, sent=sent, live=live)
    store.close()


def _setup_group(env: Env, members: list[str], *, owner: str | None = None):
    owner = owner or str(uuid.uuid4())
    g = env.groups.create_group(owner, f"g-{uuid.uuid4().hex[:8]}")
    for m in members:
        env.groups.add_member(g.group_id, m)
    return g, owner


def _make_live(env: Env, agents: list[str]) -> None:
    for m in agents:
        env.live[m] = _FakeRecord(str(uuid.uuid4()))


def test_fanout_sends_each_recipient_once(env):
    a1, a2, a3 = (str(uuid.uuid4()) for _ in range(3))
    g, owner = _setup_group(env, [a1, a2, a3])
    _make_live(env, [a1, a2, a3])

    bid = env.engine.create_broadcast(owner, g.group_id, "hello")
    result = env.engine.fan_out(bid)

    assert result.summary["total"] == 3
    assert result.summary["queued"] == 3
    assert result.summary["failures"]["count"] == 0
    assert len(env.sent) == 3


def test_sender_excluded_from_own_group(env):
    owner = str(uuid.uuid4())
    a1 = str(uuid.uuid4())
    g, _ = _setup_group(env, [owner, a1], owner=owner)
    _make_live(env, [owner, a1])

    bid = env.engine.create_broadcast(owner, g.group_id, "self-check")
    result = env.engine.fan_out(bid)

    states = {r["agent_id"]: r["state"] for r in result.per_member}
    assert states[owner] == "skipped"
    assert states[a1] == "queued"
    assert result.summary["skipped"] == 1
    assert len(env.sent) == 1


def test_partial_failure_is_explicit(env):
    a1, a2 = (str(uuid.uuid4()) for _ in range(2))
    g, owner = _setup_group(env, [a1, a2])
    _make_live(env, [a1])
    # a2 has no live session -> unreachable non-delivery.

    bid = env.engine.create_broadcast(owner, g.group_id, "partial")
    result = env.engine.fan_out(bid)

    states = {r["agent_id"]: r["state"] for r in result.per_member}
    assert states[a1] == "queued"
    assert states[a2] == "unreachable"
    assert result.summary["failures"]["count"] == 1
    assert result.summary["unreachable"] == 1


def test_retry_idempotent_no_duplicate_injection(env):
    """G3.7: re-fanning the same broadcast id never reinjects a child."""
    a1 = str(uuid.uuid4())
    g, owner = _setup_group(env, [a1])
    _make_live(env, [a1])

    bid = env.engine.create_broadcast(owner, g.group_id, "once")
    first = env.engine.fan_out(bid)
    second = env.engine.fan_out(bid)  # duplicate retry

    assert len(env.sent) == 1  # exactly one injection
    assert first.summary["total"] == second.summary["total"] == 1
    with env.store._lock:
        rows = env.store._conn.execute(
            "SELECT COUNT(*) FROM broadcast_children WHERE broadcast_id=?", (bid,)
        ).fetchone()
    assert rows[0] == 1


def test_concurrent_duplicate_broadcasters_converge(env):
    """Two concurrent fan-outs of the same broadcast -> one child each."""
    a1, a2 = (str(uuid.uuid4()) for _ in range(2))
    g, owner = _setup_group(env, [a1, a2])
    _make_live(env, [a1, a2])

    bid = env.engine.create_broadcast(owner, g.group_id, "concurrent")
    results: list = []
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        results.append(env.engine.fan_out(bid))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with env.store._lock:
        rows = env.store._conn.execute(
            "SELECT COUNT(*) FROM broadcast_children WHERE broadcast_id=?", (bid,)
        ).fetchone()
    assert rows[0] == 2
    # One send per member, not duplicated by the concurrent broadcaster.
    assert len(env.sent) == 2


def test_deterministic_child_id_stable():
    a = deterministic_child_id("b1", "agent1", "peer1")
    b = deterministic_child_id("b1", "agent1", "peer1")
    c = deterministic_child_id("b1", "agent1", "peer2")
    assert a == b
    assert a != c


def test_unknown_broadcast_rejected(env):
    with pytest.raises(ValidationError):
        env.engine.fan_out(str(uuid.uuid4()))


def test_empty_group_rejected(env):
    g, owner = _setup_group(env, [])
    bid = env.engine.create_broadcast(owner, g.group_id, "empty")
    with pytest.raises(ValidationError):
        env.engine.fan_out(bid)


def test_sender_mismatch_rejected(env):
    a1 = str(uuid.uuid4())
    g, owner = _setup_group(env, [a1])
    _make_live(env, [a1])
    bid = env.engine.create_broadcast(owner, g.group_id, "mismatch")
    with pytest.raises(ValidationError):
        env.engine.fan_out(bid, sender_agent_id=str(uuid.uuid4()))
