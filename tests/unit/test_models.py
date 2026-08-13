"""RED tests for envelope v1 model validation (AP-301)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.errors import ValidationError
from agent_peer.models import Envelope, Kind, PeerIdentity

NOW = datetime.now(UTC)


def _valid_kwargs(**overrides) -> dict:
    kwargs = {
        "protocol": "agent-peer/1",
        "message_id": str(uuid.uuid4()),
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "sender": PeerIdentity(peer_id=str(uuid.uuid4()), name="architect", profile="default"),
        "recipient_peer_id": str(uuid.uuid4()),
        "kind": Kind.MESSAGE,
        "content": "hello peer",
        "reply_to": None,
        "conversation_id": None,
        "hop_count": 0,
    }
    kwargs.update(overrides)
    return kwargs


class TestEnvelopeValidation:
    def test_valid_envelope_constructs(self):
        env = Envelope(**{**_valid_kwargs(), "kind": Kind.MESSAGE})
        assert env.protocol == "agent-peer/1"
        assert env.hop_count == 0

    @pytest.mark.parametrize("field", ["protocol", "message_id", "created_at", "expires_at", "sender", "recipient_peer_id", "kind", "content"])
    def test_missing_field_rejected(self, field):
        kwargs = _valid_kwargs()
        del kwargs[field]
        with pytest.raises((ValidationError, TypeError)):
            Envelope(**kwargs)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("protocol", "agent-peer/3"),
            ("protocol", "other/1"),
            ("message_id", "not-a-uuid"),
            ("created_at", "2026-08-09T12:00:00Z"),  # str, not datetime
            ("sender", "architect"),  # not PeerIdentity
            ("recipient_peer_id", "nope"),
            ("kind", "broadcast"),
            ("content", 42),
            ("content", b"bytes"),
            ("hop_count", -1),
            ("hop_count", 1.5),
            ("reply_to", "not-a-uuid"),
        ],
    )
    def test_wrong_type_or_value_rejected(self, field, value):
        with pytest.raises(ValidationError):
            Envelope(**{**_valid_kwargs(), field: value})

    def test_oversized_content_rejected(self):
        with pytest.raises(ValidationError):
            Envelope(**{**_valid_kwargs(), "content": "x" * (32 * 1024 + 1)})

    def test_maximum_content_accepted(self):
        env = Envelope(**{**_valid_kwargs(), "content": "x" * (32 * 1024)})
        assert len(env.content) == 32 * 1024

    def test_excessive_hops_rejected(self):
        with pytest.raises(ValidationError):
            Envelope(**{**_valid_kwargs(), "hop_count": 5})

    def test_max_hops_accepted(self):
        env = Envelope(**{**_valid_kwargs(), "hop_count": 4})
        assert env.hop_count == 4

    def test_expired_envelope_rejected(self):
        with pytest.raises(ValidationError):
            Envelope(**{**_valid_kwargs(), "expires_at": NOW - timedelta(seconds=1)})

    def test_reply_to_accepts_uuid(self):
        rid = str(uuid.uuid4())
        env = Envelope(**{**_valid_kwargs(), "reply_to": rid})
        assert env.reply_to == rid

    def test_all_kinds_valid(self):
        for kind in Kind:
            env = Envelope(**{**_valid_kwargs(), "kind": kind})
            assert env.kind is kind

    def test_immutable(self):
        env = Envelope(**_valid_kwargs())
        with pytest.raises((AttributeError, TypeError)):
            env.content = "mutated"  # type: ignore[misc]
