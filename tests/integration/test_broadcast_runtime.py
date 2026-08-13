"""Broadcast runtime integration (P4 gate): real supervisor sends.

Proves the plan's P4 gate: 1 parent -> N independent receipts, partial
failure, duplicate retry and no duplicate injection, through the real
PeerRuntimeManager transport (not injected send stubs).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from agent_peer.broadcast import BroadcastEngine
from agent_peer.groups import GroupStore
from agent_peer.models import Kind, PeerIdentity, PeerRecord, Presence, ReceiptState, make_envelope
from agent_peer.runtime import PeerRuntimeManager
from agent_peer.store import MessageStore


def _record(name: str) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        session_id=f"session-{name}",
        name=name,
        profile="default",
        agent_id=str(uuid.uuid4()),
        protocols=("agent-peer/1", "agent-peer/2"),
        started_at=datetime.now(UTC).isoformat(),
        last_seen=datetime.now(UTC).isoformat(),
        status=Presence.IDLE.value,
    )


@dataclass
class RealEnv:
    runtime: PeerRuntimeManager
    engine: BroadcastEngine
    groups: GroupStore
    store: MessageStore
    sender: PeerRecord
    sender_agent: str
    agents: list[dict]
    delivered: dict
    handles: list


def _real_broadcast(tmp_path, n_recipients: int = 3):
    runtime = PeerRuntimeManager(tmp_path)
    store = MessageStore(tmp_path / "state.sqlite3")
    groups = GroupStore(store)
    agents: list[dict] = []
    delivered: dict[str, list] = {}
    handles = []

    sender = _record("sender")
    h = runtime.register_peer(sender, on_message=lambda env: ReceiptState.QUEUED)
    handles.append(h)
    sender_agent = sender.agent_id

    for i in range(n_recipients):
        rec = _record(f"recv{i}")
        agents.append({"record": rec, "agent_id": rec.agent_id, "peer_id": rec.peer_id})
        delivered[rec.peer_id] = []
        hh = runtime.register_peer(
            rec,
            on_message=lambda env, pid=rec.peer_id: delivered[pid].append(env.content) or ReceiptState.QUEUED,
        )
        handles.append(hh)

    # Engine uses the real runtime send + registry resolve.
    def send(agent_id, peer_id, content, *, child_message_id=None):
        env = make_envelope(
            sender=PeerIdentity(peer_id=sender.peer_id, name="sender", profile="default"),
            recipient_peer_id=peer_id,
            kind=Kind.MESSAGE,
            content=content,
        )
        receipt = runtime.send(env)
        return {"state": receipt.state.value, "detail": receipt.detail}

    live = {a["agent_id"]: a["record"] for a in agents}
    live[sender_agent] = sender

    def resolve(agent_id, pin=None):
        rec = live.get(agent_id)
        return rec if rec is not None and _is_live(runtime, rec) else None

    engine = BroadcastEngine(
        store, groups, send=send, resolve=resolve, concurrency=4, max_retries=1
    )

    env = RealEnv(
        runtime=runtime,
        engine=engine,
        groups=groups,
        store=store,
        sender=sender,
        sender_agent=sender_agent,
        agents=agents,
        delivered=delivered,
        handles=handles,
    )
    yield env
    for hh in handles:
        hh.close()
    runtime.shutdown()
    store.close()


def _is_live(runtime, record) -> bool:
    return record.peer_id in runtime._peers


@pytest.fixture()
def real_env(tmp_path):
    yield from _real_broadcast(tmp_path)


def test_real_runtime_broadcast_one_parent_n_receipts(real_env):
    g = real_env.groups.create_group(real_env.sender_agent, "real-group")
    for a in real_env.agents:
        real_env.groups.add_member(g.group_id, a["agent_id"])

    bid = real_env.engine.create_broadcast(real_env.sender_agent, g.group_id, "broadcast-hi")
    result = real_env.engine.fan_out(bid)

    assert result.summary["total"] == 3
    assert result.summary["queued"] == 3
    # Each recipient actually received the content through the real transport.
    for a in real_env.agents:
        assert real_env.delivered[a["peer_id"]] == ["broadcast-hi"]


def test_real_runtime_partial_failure_and_retry(real_env):
    g = real_env.groups.create_group(real_env.sender_agent, "partial-group")
    for a in real_env.agents:
        real_env.groups.add_member(g.group_id, a["agent_id"])
    # Remove the third recipient's live registration (simulate crash/stale).
    dead = real_env.agents[2]
    real_env.runtime.unregister_peer(dead["peer_id"])
    dead_handle = [h for h in real_env.handles if h.peer_id == dead["peer_id"]]
    for h in dead_handle:
        real_env.handles.remove(h)

    bid = real_env.engine.create_broadcast(real_env.sender_agent, g.group_id, "partial-hi")
    result = real_env.engine.fan_out(bid)
    states = {r["agent_id"]: r["state"] for r in result.per_member}
    assert states[real_env.agents[0]["agent_id"]] == "queued"
    assert states[dead["agent_id"]] == "unreachable"

    # Duplicate retry: no re-injection, same outcomes.
    again = real_env.engine.fan_out(bid)
    assert again.summary["total"] == 3
    assert len(real_env.delivered[real_env.agents[0]["peer_id"]]) == 1
