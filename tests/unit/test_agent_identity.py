"""Stable agent identity tests (P3.1/P3.2, ADR-0004).

agent_id is a long-lived adapter/profile identity that survives session
rotation; peer_id stays immutable per live session. Simple adapters that
omit agent_id remain V1-only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from agent_peer.errors import ValidationError
from agent_peer.models import PeerRecord, Presence, ReceiptState


def _record(**overrides) -> PeerRecord:
    base: dict = dict(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        session_id="sess-1",
        name="alpha",
        profile="default",
        started_at=datetime.now(UTC).isoformat(),
        last_seen=datetime.now(UTC).isoformat(),
        status=Presence.IDLE.value,
    )
    base.update(overrides)
    return PeerRecord(**base)


def test_peer_record_accepts_agent_id():
    rec = _record(agent_id=str(uuid.uuid4()))
    assert rec.agent_id


def test_peer_record_defaults_agent_id_empty_for_v1():
    rec = _record()
    assert rec.agent_id == ""


def test_peer_record_rejects_non_uuid_agent_id():
    with pytest.raises(ValidationError):
        _record(agent_id="not-a-uuid")


def test_peer_record_protocols_default_v1():
    rec = _record()
    assert rec.protocols == ("agent-peer/1",)


def test_peer_record_protocols_can_advertise_v2():
    rec = _record(protocols=("agent-peer/1", "agent-peer/2"))
    assert "agent-peer/2" in rec.protocols


def test_peer_record_rejects_unknown_protocol():
    with pytest.raises(ValidationError):
        _record(protocols=("agent-peer/9",))


def test_peer_record_capabilities_default_empty():
    rec = _record()
    assert rec.capabilities == {}


def test_receipt_state_has_incompatible_and_ambiguous():
    assert ReceiptState.INCOMPATIBLE.value == "incompatible"
    assert ReceiptState.AMBIGUOUS.value == "ambiguous"


def test_session_rotation_keeps_agent_id_changes_peer_id():
    """The core session-rotation property (G2.2, P3.1): same adapter,
    different session -> same agent_id, different peer_id."""
    agent_id = str(uuid.uuid4())
    rec1 = _record(agent_id=agent_id, peer_id=str(uuid.uuid4()), session_id="s1")
    rec2 = _record(agent_id=agent_id, peer_id=str(uuid.uuid4()), session_id="s2")

    assert rec1.agent_id == rec2.agent_id
    assert rec1.peer_id != rec2.peer_id
