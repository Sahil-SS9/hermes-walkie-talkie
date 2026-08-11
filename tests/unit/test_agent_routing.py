"""Deterministic agent→peer resolution tests (P3.7, G2.5, ADR-0004).

Resolution order for an agent target:
1. pinned live peer_id -> that session
2. exactly one explicitly primary session -> that session
3. exactly one live session -> that session
4. else -> ambiguous, no delivery
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from agent_peer.discovery import DiscoveryService
from agent_peer.errors import AgentPeerError
from agent_peer.models import PeerRecord, Presence


def _record(agent_id: str, name: str, *, session_id: str = "", primary: bool = False) -> PeerRecord:
    peer_id = str(uuid.uuid4())
    return PeerRecord(
        peer_id=peer_id,
        instance_id=str(uuid.uuid4()),
        session_id=session_id or f"sess-{name}",
        name=name,
        profile="default",
        agent_id=agent_id,
        protocols=("agent-peer/1", "agent-peer/2"),
        capabilities={"primary": primary},
        started_at=datetime.now(UTC).isoformat(),
        last_seen=datetime.now(UTC).isoformat(),
        status=Presence.IDLE.value,
        socket_path=f"/tmp/fake-{peer_id}.sock",
    )


class _FakeRegistry:
    """Registry stub returning a fixed live record list (no disk)."""

    def __init__(self, records: list[PeerRecord]) -> None:
        self._records = records
        self._live = {r.peer_id for r in records}

    def set_live(self, peer_ids: set[str]) -> None:
        self._live = set(peer_ids)

    def list_peers(self) -> list[PeerRecord]:
        return self._records

    def get(self, peer_id: str) -> PeerRecord | None:
        return next((r for r in self._records if r.peer_id == peer_id), None)


class _FakeBackend:
    """Backend that answers DISCOVER probes for records in the live set."""

    kind = "posix"

    def __init__(self, registry: _FakeRegistry) -> None:
        self._registry = registry

    def probe(self, endpoint, challenge, *, timeout: float) -> bytes:
        raise AgentPeerError("unused")

    def bound(self, endpoint, *, timeout: float) -> bool:
        return True

    def request(self, endpoint, frame, *, timeout: float) -> bytes:
        """Decode the DISCOVER envelope; reply ALIVE for a live record."""
        import json as _json

        from agent_peer.codec import decode_envelope, encode_envelope
        from agent_peer.models import Kind, PeerIdentity, make_envelope

        env = decode_envelope(frame)
        if env.kind is not Kind.DISCOVER:
            raise AgentPeerError("not a discover probe")
        rec = self._registry.get(env.recipient_peer_id)
        if rec is None or rec.peer_id not in self._registry._live:
            raise AgentPeerError("not live")
        identity = _json.dumps(
            {
                "nonce": env.conversation_id or "",
                "peer_id": rec.peer_id,
                "instance_id": rec.instance_id,
                "session_id": rec.session_id,
                "agent_id": rec.agent_id,
                "protocols": list(rec.protocols),
                "capabilities": rec.capabilities,
                "protocol": rec.protocol,
                "status": rec.status,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        reply = make_envelope(
            sender=PeerIdentity(peer_id=rec.peer_id, name=rec.name, profile=rec.profile),
            recipient_peer_id=env.sender.peer_id,
            kind=Kind.ALIVE,
            content=identity,
            conversation_id=env.conversation_id,
        )
        return encode_envelope(reply).encode("utf-8")

    def close(self) -> None:
        pass


def _service(records: list[PeerRecord]) -> DiscoveryService:
    reg = _FakeRegistry(records)
    svc = DiscoveryService.__new__(DiscoveryService)
    svc._registry = reg
    svc._backend = _FakeBackend(reg)
    svc._paths = None
    return svc


def test_agent_single_live_session_resolves():
    agent = str(uuid.uuid4())
    rec = _record(agent, "alpha", session_id="s1")
    svc = _service([rec])

    result = svc.resolve_agent(agent)

    assert result is not None
    assert result.peer_id == rec.peer_id


def test_agent_multiple_live_sessions_ambiguous():
    agent = str(uuid.uuid4())
    r1 = _record(agent, "alpha", session_id="s1")
    r2 = _record(agent, "alpha", session_id="s2")
    svc = _service([r1, r2])

    with pytest.raises(AgentPeerError):
        svc.resolve_agent(agent)


def test_agent_primary_session_wins():
    agent = str(uuid.uuid4())
    r1 = _record(agent, "alpha", session_id="s1")
    r2 = _record(agent, "alpha", session_id="s2", primary=True)
    svc = _service([r1, r2])

    result = svc.resolve_agent(agent)

    assert result is not None
    assert result.peer_id == r2.peer_id


def test_agent_unknown_fails_closed():
    svc = _service([])
    with pytest.raises(AgentPeerError):
        svc.resolve_agent(str(uuid.uuid4()))


def test_pinned_peer_id_resolves_directly():
    agent = str(uuid.uuid4())
    r1 = _record(agent, "alpha", session_id="s1")
    r2 = _record(agent, "alpha", session_id="s2")
    svc = _service([r1, r2])

    result = svc.resolve_agent(agent, pinned_peer_id=r2.peer_id)

    assert result is not None
    assert result.peer_id == r2.peer_id


def test_primary_with_multiple_primaries_ambiguous():
    agent = str(uuid.uuid4())
    r1 = _record(agent, "alpha", session_id="s1", primary=True)
    r2 = _record(agent, "alpha", session_id="s2", primary=True)
    svc = _service([r1, r2])

    with pytest.raises(AgentPeerError):
        svc.resolve_agent(agent)


def test_agent_with_no_agent_id_is_v1_only():
    """A record without agent_id is V1-only: never resolvable by agent."""
    rec = _record("", "alpha", session_id="s1")
    svc = _service([rec])
    with pytest.raises(AgentPeerError):
        svc.resolve_agent(str(uuid.uuid4()))
