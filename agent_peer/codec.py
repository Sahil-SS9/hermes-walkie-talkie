"""Canonical JSON codec and length-prefixed framing for agent-peer/1 (AP-304, AP-305).

- Canonical JSON: sorted keys, compact separators, UTF-8 — stable across
  runs for tests, logs and hashing.
- Framing: 4-byte big-endian length prefix + UTF-8 JSON payload over
  ``AF_UNIX`` + ``SOCK_STREAM``. Length prefixes above the hard ceiling are
  rejected BEFORE payload buffering (bounded allocation).
- Decoding never executes objects: plain ``json.loads`` only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .constants import FRAME_LENGTH_PREFIX_BYTES, MAX_FRAME_BYTES, PROTOCOL_ID, PROTOCOL_ID_V2
from .errors import FrameError, OversizedError, UnsupportedVersionError, ValidationError
from .models import Envelope, Kind, PeerIdentity, ReceiptState


def canonical_json(obj: Any) -> str:
    """Serialise *obj* to canonical JSON (sorted keys, compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _rfc3339(dt: datetime) -> str:
    """RFC3339 UTC with 'Z' suffix and microsecond precision."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _parse_rfc3339(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text).astimezone(UTC)


def _envelope_to_dict(env: Envelope) -> dict:
    return {
        "protocol": env.protocol,
        "message_id": env.message_id,
        "created_at": _rfc3339(env.created_at),
        "expires_at": _rfc3339(env.expires_at),
        "sender": {
            "peer_id": env.sender.peer_id,
            "name": env.sender.name,
            "profile": env.sender.profile,
        },
        "recipient_peer_id": env.recipient_peer_id,
        "kind": env.kind.value,
        "content": env.content,
        "reply_to": env.reply_to,
        "conversation_id": env.conversation_id,
        "hop_count": env.hop_count,
    }


def encode_envelope(env: Envelope) -> str:
    """Encode an envelope to canonical JSON text (no framing)."""
    return canonical_json(_envelope_to_dict(env))


def encode_frame(payload: str) -> bytes:
    """Frame a canonical JSON string: 4-byte big-endian length + payload."""
    body = payload.encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise OversizedError(f"frame payload {len(body)} bytes exceeds {MAX_FRAME_BYTES}")
    return len(body).to_bytes(FRAME_LENGTH_PREFIX_BYTES, "big") + body


def _dict_to_envelope(data: dict, now: datetime | None = None) -> Envelope:
    """Build an Envelope from a decoded dict, raising ValidationError."""
    try:
        sender_raw = data["sender"]
        sender = PeerIdentity(
            peer_id=sender_raw["peer_id"],
            name=sender_raw.get("name", ""),
            profile=sender_raw.get("profile", ""),
        )
        env = Envelope(
            protocol=data["protocol"],
            message_id=data["message_id"],
            created_at=_parse_rfc3339(data["created_at"]),
            expires_at=_parse_rfc3339(data["expires_at"]),
            sender=sender,
            recipient_peer_id=data["recipient_peer_id"],
            kind=Kind(data["kind"]),
            content=data["content"],
            reply_to=data.get("reply_to"),
            conversation_id=data.get("conversation_id"),
            hop_count=data.get("hop_count", 0),
        )
        if env.is_expired(now):
            raise ValidationError("envelope expired")
        return env
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"malformed envelope: {exc}") from exc


def decode_envelope(payload: bytes) -> Envelope:
    """Decode a framed envelope payload. Raises protocol errors."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrameError(f"invalid UTF-8 payload: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FrameError(f"malformed JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FrameError("envelope root must be a JSON object")
    protocol = data.get("protocol")
    if protocol not in (PROTOCOL_ID, PROTOCOL_ID_V2):
        raise UnsupportedVersionError(f"unsupported protocol {protocol!r}")
    try:
        return _dict_to_envelope(data)
    except ValidationError as exc:
        raise exc


def decode_envelope_safe(payload: bytes, now: datetime | None = None) -> tuple[Envelope | None, str | None]:
    """Decode without raising; return ``(envelope, None)`` or ``(None, state)``.

    The state string is one of the ReceiptState values (``invalid``,
    ``expired``), so unknown major versions and malformed input fail closed
    with an explicit receipt instead of crashing the supervisor.
    """
    try:
        env = decode_envelope(payload)
    except UnsupportedVersionError:
        return None, ReceiptState.INVALID.value
    except ValidationError as exc:
        if "expired" in str(exc):
            return None, ReceiptState.EXPIRED.value
        return None, ReceiptState.INVALID.value
    except FrameError:
        return None, ReceiptState.INVALID.value
    if env.is_expired(now):
        return None, ReceiptState.EXPIRED.value
    return env, None


class FrameDecoder:
    """Incremental length-prefixed frame decoder for stream sockets.

    Feed bytes with :meth:`feed`; complete frames yield :class:`Envelope`
    objects. Oversized length prefixes are rejected immediately, before any
    payload is buffered.
    """

    __slots__ = ("_buffer", "_expected")

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._expected: int | None = None

    def feed(self, data: bytes):
        """Consume *data*, yielding decoded envelopes as frames complete."""
        self._buffer.extend(data)
        while True:
            if self._expected is None:
                if len(self._buffer) < FRAME_LENGTH_PREFIX_BYTES:
                    return
                raw_len = bytes(self._buffer[:FRAME_LENGTH_PREFIX_BYTES])
                length = int.from_bytes(raw_len, "big")
                if length > MAX_FRAME_BYTES:
                    raise OversizedError(
                        f"frame length {length} exceeds ceiling {MAX_FRAME_BYTES}"
                    )
                self._expected = length
                del self._buffer[:FRAME_LENGTH_PREFIX_BYTES]
            if len(self._buffer) < self._expected:
                return
            payload = bytes(self._buffer[: self._expected])
            del self._buffer[: self._expected]
            self._expected = None
            try:
                yield decode_envelope(payload)
            except UnsupportedVersionError:
                raise
            except ValidationError as exc:
                raise FrameError(str(exc)) from exc
