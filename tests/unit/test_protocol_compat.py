"""Protocol compatibility tests (AP-306): v1 accepts v1; unknown majors -> invalid."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.codec import decode_envelope_safe, encode_envelope
from agent_peer.models import Envelope, Kind, PeerIdentity

NOW = datetime.now(UTC)


def _envelope() -> Envelope:
    return Envelope(
        protocol="agent-peer/1",
        message_id=str(uuid.uuid4()),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="architect", profile="default"),
        recipient_peer_id=str(uuid.uuid4()),
        kind=Kind.MESSAGE,
        content="v1 accepts v1",
        reply_to=None,
        conversation_id=None,
        hop_count=0,
    )


class TestCompatibility:
    def test_v1_accepts_v1(self):
        raw = encode_envelope(_envelope())
        decoded, error = decode_envelope_safe(raw.encode("utf-8"))
        assert error is None
        assert decoded.protocol == "agent-peer/1"

    @pytest.mark.parametrize("bad_protocol", ["agent-peer/2", "agent-peer/9", "other/1", "agent-peer", ""])
    def test_unknown_versions_return_invalid_without_crashing(self, bad_protocol):
        raw = encode_envelope(_envelope()).replace("agent-peer/1", bad_protocol)
        decoded, error = decode_envelope_safe(raw.encode("utf-8"))
        assert decoded is None
        assert error == "invalid"

    def test_protocol_id_constant(self):
        import agent_peer

        assert agent_peer.PROTOCOL_ID == "agent-peer/1"
