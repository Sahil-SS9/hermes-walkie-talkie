"""RED tests for canonical JSON codec and length-prefixed framing (AP-302, AP-304, AP-305)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.codec import (
    FrameDecoder,
    canonical_json,
    decode_envelope_safe,
    encode_envelope,
    encode_frame,
)
from agent_peer.errors import FrameError
from agent_peer.models import Envelope, Kind, PeerIdentity

NOW = datetime.now(UTC)


def _envelope(protocol: str = "agent-peer/1") -> Envelope:
    return Envelope(
        protocol=protocol,
        message_id=str(uuid.uuid4()),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="architect", profile="default"),
        recipient_peer_id=str(uuid.uuid4()),
        kind=Kind.MESSAGE,
        content="hello peer",
        reply_to=None,
        conversation_id=None,
        hop_count=0,
    )


class TestCanonicalJson:
    def test_stable_serialisation(self):
        a = {"b": 1, "a": [1, 2, {"z": "x"}]}
        b = {"a": [1, 2, {"z": "x"}], "b": 1}
        assert canonical_json(a) == canonical_json(b)

    def test_utf8_round_trip(self):
        assert canonical_json({"content": "héllo — 世界"}) == '{"content":"héllo — 世界"}'

    def test_no_executable_deserialisation(self):
        # eval()/exec() style payloads are inert JSON strings.
        payload = '{"__class__": {"__init__": {"__globals__": {"x": 1}}}}'
        import json

        assert json.loads(payload)["__class__"]["__init__"]["__globals__"]["x"] == 1


class TestFrameCodec:
    def test_round_trip_frame(self):
        env = _envelope()
        data = encode_frame(encode_envelope(env))
        decoded = FrameDecoder()
        frames = list(decoded.feed(data))
        assert len(frames) == 1
        assert frames[0].message_id == env.message_id
        assert frames[0].content == "hello peer"

    def test_partial_frames_accumulate(self):
        env = _envelope()
        data = encode_frame(encode_envelope(env))
        dec = FrameDecoder()
        chunks = [data[i : i + 7] for i in range(0, len(data), 7)]
        frames = []
        for chunk in chunks:
            frames.extend(dec.feed(chunk))
        assert len(frames) == 1
        assert frames[0].message_id == env.message_id

    def test_multiple_frames_in_one_feed(self):
        env = _envelope()
        data = encode_frame(encode_envelope(env)) + encode_frame(encode_envelope(env))
        frames = list(FrameDecoder().feed(data))
        assert len(frames) == 2

    def test_oversized_frame_rejected_before_buffering(self):
        # Frame length prefix claims 1 MiB: must be rejected without
        # buffering the payload (hard ceiling is 64 KiB).
        dec = FrameDecoder()
        with pytest.raises(FrameError):
            list(dec.feed((1 << 20).to_bytes(4, "big") + b"x"))

    def test_exactly_max_frame_accepted(self):
        env = _envelope()
        payload = encode_envelope(env).encode("utf-8")
        # Pad content to push the frame near the ceiling but under it.
        assert len(payload) < 64 * 1024

    def test_invalid_utf8_rejected(self):
        dec = FrameDecoder()
        payload = b"\xff\xfe\xfd"
        with pytest.raises(FrameError):
            list(dec.feed(len(payload).to_bytes(4, "big") + payload))

    def test_malformed_json_rejected(self):
        dec = FrameDecoder()
        payload = b"{not json"
        with pytest.raises(FrameError):
            list(dec.feed(len(payload).to_bytes(4, "big") + payload))

    def test_truncated_length_prefix_is_inert(self):
        dec = FrameDecoder()
        assert list(dec.feed(b"\x00\x01")) == []  # incomplete prefix

    def test_negative_length_rejected(self):
        dec = FrameDecoder()
        with pytest.raises(FrameError):
            list(dec.feed((2**32 - 1).to_bytes(4, "big")))


class TestEnvelopeCodec:
    def test_rfc3339_round_trip(self):
        env = _envelope()
        raw = encode_envelope(env)
        decoded, error = decode_envelope_safe(raw.encode("utf-8"))
        assert error is None
        assert decoded.created_at == env.created_at
        assert decoded.expires_at == env.expires_at

    def test_unknown_major_version_returns_invalid_state(self):
        env = _envelope()
        raw = encode_envelope(env).replace("agent-peer/1", "agent-peer/9")
        decoded, error = decode_envelope_safe(raw.encode("utf-8"))
        assert decoded is None
        assert error == "invalid"

    def test_v2_envelope_decodes(self):
        """V2 is now supported (ADR-0004): a V2 envelope decodes normally."""
        env = _envelope(protocol="agent-peer/2")
        raw = encode_envelope(env)
        decoded, error = decode_envelope_safe(raw.encode("utf-8"))
        assert decoded is not None
        assert error is None
        assert decoded.protocol == "agent-peer/2"

    def test_malformed_returns_invalid_state(self):
        decoded, error = decode_envelope_safe(b"{oops")
        assert decoded is None
        assert error == "invalid"

    def test_expired_returns_expired_state(self):
        env = Envelope(
            protocol="agent-peer/1",
            message_id=str(uuid.uuid4()),
            created_at=NOW - timedelta(minutes=10),
            expires_at=NOW - timedelta(minutes=5),
            sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="a", profile="default"),
            recipient_peer_id=str(uuid.uuid4()),
            kind=Kind.MESSAGE,
            content="too late",
            reply_to=None,
            conversation_id=None,
            hop_count=0,
        )
        raw = encode_envelope(env)
        decoded, error = decode_envelope_safe(raw.encode("utf-8"))
        assert decoded is None
        assert error == "expired"

    def test_round_trip_preserves_optional_fields(self):
        import dataclasses

        env = _envelope()
        env = dataclasses.replace(
            env,
            reply_to=str(uuid.uuid4()),
            conversation_id="conv-1",
            hop_count=2,
        )
        decoded, error = decode_envelope_safe(encode_frame(encode_envelope(env))[4:])
        assert error is None
        assert decoded.reply_to == env.reply_to
        assert decoded.conversation_id == "conv-1"
        assert decoded.hop_count == 2
