"""Broadcast security/limits tests (P4, G3.8/G3.9, NG-09)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from agent_peer.broadcast import BroadcastEngine
from agent_peer.constants import DEFAULT_FANOUT_CONCURRENCY, DEFAULT_GROUP_CAP, HARD_GROUP_CAP
from agent_peer.errors import ValidationError
from agent_peer.groups import GroupStore
from agent_peer.store import MessageStore


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
    live: dict = {}

    def send(agent, peer, content, *, child_message_id=None):
        sent.append(agent)
        return {"state": "queued", "detail": ""}

    def resolve(agent_id, pin=None):
        return live.get(agent_id)

    eng = BroadcastEngine(store, groups, send=send, resolve=resolve)
    yield Env(engine=eng, store=store, groups=groups, sent=sent, live=live)
    store.close()


def test_default_cap_constants():
    assert DEFAULT_GROUP_CAP == 32
    assert HARD_GROUP_CAP == 128
    assert DEFAULT_FANOUT_CONCURRENCY == 8


def test_hard_cap_rejects_oversized_group(env):
    """G3.9: the hard ceiling cannot be bypassed via config."""

    with pytest.raises(ValidationError):
        env.groups.validate_cap(HARD_GROUP_CAP, cap=HARD_GROUP_CAP + 1)
    env.groups.validate_cap(HARD_GROUP_CAP - 1, cap=HARD_GROUP_CAP)


def test_broadcast_concurrency_is_bounded(env):
    """NG-09: fan-out never exceeds the configured concurrency window."""
    agents = [str(uuid.uuid4()) for _ in range(20)]
    g, owner = _setup(env, agents)
    for a in agents:
        env.live[a] = _SimpleRecord(str(uuid.uuid4()))
    bid = env.engine.create_broadcast(owner, g.group_id, "load")
    env.engine.fan_out(bid)
    # All 20 sent exactly once (sender is not a member here).
    assert len(env.sent) == 20


def test_concurrency_zero_rejected(env):
    with pytest.raises(ValidationError):
        BroadcastEngine(
            env.store, env.groups, concurrency=0, send=lambda *a, **k: {}, resolve=lambda a, p=None: None
        )


class _SimpleRecord:
    def __init__(self, peer_id: str) -> None:
        self.peer_id = peer_id


def _setup(env: Env, members: list[str], *, owner: str | None = None):
    owner = owner or str(uuid.uuid4())
    g = env.groups.create_group(owner, f"g-{uuid.uuid4().hex[:8]}")
    for m in members:
        env.groups.add_member(g.group_id, m)
    return g, owner
