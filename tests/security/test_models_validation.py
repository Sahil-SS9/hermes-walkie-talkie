"""Trust-path validation error branches (models.py, coverage gate).

Exercises every fail-closed validation branch in the wire models: a
malformed envelope from the socket must raise, never pass through.
"""

from __future__ import annotations

import pytest

from agent_peer.errors import ValidationError
from agent_peer.models import (
    MAX_CONTENT_BYTES,
    Envelope,
    Kind,
    PeerIdentity,
    PeerRecord,
    Presence,
    Receipt,
    ReceiptState,
    make_envelope,
)

NOW = "2026-01-01T00:00:00+00:00"
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
UUID_C = "33333333-3333-4333-8333-333333333333"


def _peer_record(**over) -> PeerRecord:
    base = dict(
        peer_id=UUID_A,
        instance_id=UUID_B,
        session_id="s1",
        name="p",
        profile="",
        surface="cli",
        started_at=NOW,
        last_seen=NOW,
        status=Presence.IDLE.value,
    )
    base.update(over)
    return PeerRecord(**base)


class TestModelsValidation:
    def test_naive_datetime_rejected(self):
        from datetime import datetime

        with pytest.raises(ValidationError):
            Envelope(
                protocol="agent-peer/1",
                message_id=UUID_C,
                created_at=datetime.fromisoformat("2026-01-01T00:00:00"),  # naive
                expires_at=datetime.fromisoformat("2026-01-01T00:01:00+00:00"),
                sender=PeerIdentity(peer_id=UUID_B),
                recipient_peer_id=UUID_A,
                kind=Kind.MESSAGE,
                content="x",
                hop_count=0,
            )

    def test_peer_identity_non_string_fields(self):
        with pytest.raises(ValidationError):
            PeerIdentity(peer_id=UUID_B, name=123)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            PeerIdentity(peer_id=UUID_B, profile=[])  # type: ignore[arg-type]

    def test_peer_record_protocols_not_tuple(self):
        with pytest.raises(ValidationError):
            _peer_record(protocols="v1")  # type: ignore[arg-type]

    def test_peer_record_capabilities_not_dict(self):
        with pytest.raises(ValidationError):
            _peer_record(capabilities=["a"])  # type: ignore[arg-type]

    def test_peer_record_bad_status(self):
        with pytest.raises(ValidationError):
            _peer_record(status="zombie")

    def test_peer_record_bad_protocol(self):
        with pytest.raises(ValidationError):
            _peer_record(protocol="v9")

    def test_envelope_kind_not_kind(self):
        with pytest.raises(ValidationError):
            make_envelope(
                message_id=UUID_C,
                kind=object(),  # type: ignore[arg-type]
                content="x",
                sender=PeerIdentity(peer_id=UUID_B),
                recipient_peer_id=UUID_A,
            )

    def test_envelope_bad_conversation_id(self):
        with pytest.raises(ValidationError):
            make_envelope(
                message_id=UUID_C,
                kind=Kind.MESSAGE,
                content="x",
                sender=PeerIdentity(peer_id=UUID_B),
                recipient_peer_id=UUID_A,
                conversation_id=7,  # type: ignore[arg-type]
            )

    def test_envelope_content_over_limit(self):
        with pytest.raises(ValidationError):
            make_envelope(
                message_id=UUID_C,
                kind=Kind.MESSAGE,
                content="x" * (MAX_CONTENT_BYTES + 1),
                sender=PeerIdentity(peer_id=UUID_B),
                recipient_peer_id=UUID_A,
            )

    def test_receipt_bad_state(self):
        with pytest.raises(ValidationError):
            Receipt(message_id=UUID_C, state="bogus", recipient_peer_id=UUID_A)  # type: ignore[arg-type]

    def test_receipt_valid_state_passes(self):
        r = Receipt(message_id=UUID_C, state=ReceiptState.QUEUED, recipient_peer_id=UUID_A)
        assert r.state is ReceiptState.QUEUED
        assert r.as_dict()["state"] == "queued"
