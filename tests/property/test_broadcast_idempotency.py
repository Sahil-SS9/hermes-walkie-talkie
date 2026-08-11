"""Broadcast idempotency property tests (P4.7, G3.7)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_peer.broadcast import BroadcastEngine, deterministic_child_id
from agent_peer.groups import GroupStore
from agent_peer.store import MessageStore

_AGENTS = st.lists(
    st.uuids().map(str), min_size=1, max_size=16, unique=True
)


@dataclass
class Env:
    engine: BroadcastEngine
    store: MessageStore
    groups: GroupStore
    sent: list
    live: dict


def _make_env(tmp_path):
    store = MessageStore(tmp_path / "messages.sqlite3")
    groups = GroupStore(store)
    sent: list[dict] = []
    live: dict = {}

    def send(agent, peer, content, *, child_message_id=None):
        sent.append(child_message_id)
        return {"state": "queued", "detail": ""}

    def resolve(agent_id, pin=None):
        rec = live.get(agent_id)
        return rec  # type: ignore[no-any-return]

    eng = BroadcastEngine(store, groups, send=send, resolve=resolve, concurrency=4, max_retries=1)
    return Env(engine=eng, store=store, groups=groups, sent=sent, live=live)


class _Rec:
    def __init__(self, peer_id: str) -> None:
        self.peer_id = peer_id


@given(_AGENTS)
@settings(max_examples=40, deadline=10_000)
def test_retry_never_injects_duplicate(agents: list[str]):
    """Re-fanning any broadcast id yields exactly one child per recipient."""
    import tempfile
    from pathlib import Path

    env = _make_env(Path(tempfile.mkdtemp(prefix="prop-bcast-")))
    try:
        owner = str(uuid.uuid4())
        g = env.groups.create_group(owner, "prop-group")
        for a in agents:
            env.groups.add_member(g.group_id, a)
            env.live[a] = _Rec(str(uuid.uuid4()))
        # Owner is not a member here, so every agent is a recipient.
        bid = env.engine.create_broadcast(owner, g.group_id, "prop")
        first = env.engine.fan_out(bid)
        second = env.engine.fan_out(bid)
        third = env.engine.fan_out(bid)

        assert first.summary["total"] == len(agents)
        assert second.summary["total"] == len(agents)
        assert third.summary["total"] == len(agents)
        # Exactly one injection per recipient across all retries.
        assert len(env.sent) == len(agents)
        with env.store._lock:
            rows = env.store._conn.execute(
                "SELECT COUNT(*) FROM broadcast_children WHERE broadcast_id=?", (bid,)
            ).fetchone()
        assert rows[0] == len(agents)
    finally:
        env.store.close()


@given(st.uuids().map(str), st.uuids().map(str), st.uuids().map(str))
@settings(max_examples=100)
def test_child_id_is_function_of_triple(bid: str, agent: str, peer: str):
    """deterministic_child_id is a pure function of its three inputs."""
    assert deterministic_child_id(bid, agent, peer) == deterministic_child_id(bid, agent, peer)
