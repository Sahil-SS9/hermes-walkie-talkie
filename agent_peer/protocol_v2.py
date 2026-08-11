"""agent-peer/2 protocol module (P3.4, ADR-0004).

V2 adds typed discriminated payloads over the existing framed transport:
``message``, ``receipt``, ``request``, ``request_status``, ``request_cancel``,
``discover``, ``alive``. Payloads are strictly validated bounded JSON; unknown
or oversized shapes are rejected BEFORE persistence or delivery.

The wire envelope shape stays the same as V1 (codec.Envelope) — V2 is the
protocol id ``agent-peer/2`` plus these typed content payloads.
"""

from __future__ import annotations

import json
from typing import Any

from .constants import MAX_CONTENT_BYTES
from .errors import ValidationError


class V2Payload:
    """Base for strictly validated V2 payloads."""

    kind: str = ""
    _fields: tuple[str, ...] = ()

    def to_content(self) -> str:
        data = {"kind": self.kind, **{name: getattr(self, name) for name in self._fields}}
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_content(cls, content: str) -> V2Payload:
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValidationError("V2 payload exceeds content ceiling")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"V2 payload not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValidationError("V2 payload must be a JSON object")
        if data.get("kind") != cls.kind:
            raise ValidationError(f"payload kind mismatch: expected {cls.kind}")
        missing = [f for f in cls._fields if f not in data]
        if missing:
            raise ValidationError(f"V2 payload missing fields: {missing}")
        extra = set(data) - set(cls._fields) - {"kind"}
        if extra:
            raise ValidationError(f"V2 payload unknown fields: {sorted(extra)}")
        return cls(**{f: data[f] for f in cls._fields})


class MessagePayload(V2Payload):
    kind = "message"
    _fields = ("text",)

    def __init__(self, text: str) -> None:
        if not isinstance(text, str):
            raise ValidationError("message text must be a string")
        self.text = text


class ReceiptPayload(V2Payload):
    kind = "receipt"
    _fields = ("state", "detail")

    def __init__(self, state: str, detail: str = "") -> None:
        if not isinstance(state, str):
            raise ValidationError("receipt state must be a string")
        self.state = state
        self.detail = detail


class DiscoverPayload(V2Payload):
    kind = "discover"
    _fields = ("nonce",)

    def __init__(self, nonce: str) -> None:
        if not isinstance(nonce, str):
            raise ValidationError("discover nonce must be a string")
        self.nonce = nonce


class AlivePayload(V2Payload):
    kind = "alive"
    _fields = ("peer_id", "instance_id", "agent_id", "protocols", "capabilities", "protocol", "status")

    def __init__(
        self,
        peer_id: str,
        instance_id: str,
        agent_id: str = "",
        protocols: list[str] | None = None,
        capabilities: dict[str, Any] | None = None,
        protocol: str = "agent-peer/1",
        status: str = "idle",
    ) -> None:
        self.peer_id = peer_id
        self.instance_id = instance_id
        self.agent_id = agent_id
        self.protocols = protocols or []
        self.capabilities = capabilities or {}
        self.protocol = protocol
        self.status = status


class RequestPayload(V2Payload):
    kind = "request"
    _fields = ("request_id", "sender_agent_id", "recipient_agent_id", "state", "summary")

    def __init__(
        self,
        request_id: str,
        sender_agent_id: str,
        recipient_agent_id: str,
        state: str,
        summary: str,
    ) -> None:
        self.request_id = request_id
        self.sender_agent_id = sender_agent_id
        self.recipient_agent_id = recipient_agent_id
        self.state = state
        self.summary = summary


class RequestStatusPayload(V2Payload):
    kind = "request_status"
    _fields = ("request_id", "state", "detail")

    def __init__(self, request_id: str, state: str, detail: str = "") -> None:
        self.request_id = request_id
        self.state = state
        self.detail = detail


class RequestCancelPayload(V2Payload):
    kind = "request_cancel"
    _fields = ("request_id",)

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id


_PAYLOADS = {
    p.kind: p
    for p in (
        MessagePayload,
        ReceiptPayload,
        DiscoverPayload,
        AlivePayload,
        RequestPayload,
        RequestStatusPayload,
        RequestCancelPayload,
    )
}

KNOWN_KINDS = frozenset(_PAYLOADS)


def decode_v2_payload(kind: str, content: str) -> Any:
    """Decode a strict V2 payload by kind. Unknown kind raises ValidationError.

    Returns the concrete payload class instance (the caller knows the kind it
    requested); typed as ``Any`` because the factory dispatches per kind.
    """
    cls = _PAYLOADS.get(kind)
    if cls is None:
        raise ValidationError(f"unknown V2 payload kind {kind!r}")
    return cls.from_content(content)


__all__ = [
    "AlivePayload",
    "DiscoverPayload",
    "KNOWN_KINDS",
    "MessagePayload",
    "ReceiptPayload",
    "RequestCancelPayload",
    "RequestPayload",
    "RequestStatusPayload",
    "V2Payload",
    "decode_v2_payload",
]
