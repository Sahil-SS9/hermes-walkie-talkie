"""Immutable protocol models for agent-peer/1 (ADR-0003).

Validation is eager: constructing an :class:`Envelope` (or any model) with an
invalid field raises :class:`~agent_peer.errors.ValidationError`.
"""

from __future__ import annotations

import enum
import re
import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .constants import MAX_CONTENT_BYTES, MAX_HOP_COUNT, PROTOCOL_ID, PROTOCOL_ID_V2
from .errors import ValidationError

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class Kind(str, enum.Enum):
    """Allowed envelope kinds (ADR-0003).

    ``discover``/``alive`` are the control kinds used by the liveness
    challenge-response (REM-107). They ride the existing framed Unix
    transport and never create a second control plane.
    """

    PING = "ping"
    PONG = "pong"
    MESSAGE = "message"
    RECEIPT = "receipt"
    DISCOVER = "discover"
    ALIVE = "alive"


class ReceiptState(str, enum.Enum):
    """Immediate receipt states (ADR-0003) + V2 result states (ADR-0004).

    ``incompatible``/``ambiguous`` are V2 result states: a peer that cannot
    perform a group/workflow operation returns ``incompatible`` (never a
    free-text fallback), and an agent target that resolves to more than one
    live session returns ``ambiguous`` with no delivery (G2.5, P3.5).
    V1 state meanings are unchanged.
    """

    QUEUED = "queued"
    HELD = "held"
    REFUSED = "refused"
    UNREACHABLE = "unreachable"
    EXPIRED = "expired"
    INVALID = "invalid"
    RATE_LIMITED = "rate_limited"
    OVER_CAPACITY = "over_capacity"
    INCOMPATIBLE = "incompatible"
    AMBIGUOUS = "ambiguous"


class Policy(str, enum.Enum):
    """Receiver inbound policy."""

    ACCEPT = "accept"
    HOLD = "hold"
    REFUSE = "refuse"


class Presence(str, enum.Enum):
    """Peer presence states (AP-405)."""

    IDLE = "idle"
    WORKING = "working"
    HELD = "held"
    CLOSING = "closing"


class Surface(str, enum.Enum):
    """Host surface names."""

    CLI = "cli"
    TUI = "tui"
    GATEWAY = "gateway"
    DESKTOP = "desktop"


def _require_uuid(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise ValidationError(f"{name} must be a UUID string, got {value!r}")
    return value


def _require_utc_datetime(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValidationError(f"{name} must be timezone-aware (RFC3339 UTC)")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PeerIdentity:
    """Immutable sender/recipient identity inside envelopes."""

    peer_id: str
    name: str = ""
    profile: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "peer_id", _require_uuid("peer_id", self.peer_id))
        if not isinstance(self.name, str):
            raise ValidationError("name must be a string")
        if not isinstance(self.profile, str):
            raise ValidationError("profile must be a string")


@dataclass(frozen=True, slots=True)
class PeerRecord:
    """One registry entry describing a live peer (AP-403..AP-405, REM-105).

    ``socket_uid`` and ``socket_inode`` are captured from the actual bound
    listener before publication (registration order, REM-106) and are used
    by the discovery fence (REM-108/111) to refuse cleanup of a replaced or
    mismatched socket.
    """

    peer_id: str
    instance_id: str
    session_id: str = ""
    name: str = ""
    profile: str = ""
    agent_id: str = ""            # long-lived adapter/profile identity (V2)
    protocols: tuple[str, ...] = field(default_factory=tuple)  # advertised supported protocol IDs
    capabilities: dict = field(default_factory=dict)  # advertised V2 capability flags
    surface: str = "cli"
    host_target: str = ""          # opaque Hermes-owned routing token
    pid: int = 0
    cwd: str = ""
    git_repo_root: str = ""
    git_branch: str = ""
    started_at: str = ""           # RFC3339 UTC
    last_seen: str = ""            # RFC3339 UTC
    status: str = Presence.IDLE.value
    socket_path: str = ""
    socket_uid: int = 0
    socket_inode: int = 0
    protocol: str = PROTOCOL_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "peer_id", _require_uuid("peer_id", self.peer_id))
        object.__setattr__(self, "instance_id", _require_uuid("instance_id", self.instance_id))
        if self.agent_id:
            object.__setattr__(self, "agent_id", _require_uuid("agent_id", self.agent_id))
        if not isinstance(self.protocols, tuple | list):
            raise ValidationError("protocols must be a tuple of protocol IDs")
        protocols = tuple(self.protocols) or (PROTOCOL_ID,)
        known = {PROTOCOL_ID, PROTOCOL_ID_V2}
        if not all(isinstance(p, str) and p in known for p in protocols):
            raise ValidationError(f"invalid protocol advertisement {self.protocols!r}")
        object.__setattr__(self, "protocols", protocols)
        if not isinstance(self.capabilities, dict):
            raise ValidationError("capabilities must be a dict")
        if self.status not in {p.value for p in Presence}:
            raise ValidationError(f"invalid presence status {self.status!r}")
        if self.protocol != PROTOCOL_ID and self.protocol != PROTOCOL_ID_V2:
            raise ValidationError(f"unsupported protocol {self.protocol!r}")


@dataclass(frozen=True, slots=True)
class Envelope:
    """agent-peer/1 message envelope (ADR-0003 §4.3)."""

    protocol: str
    message_id: str
    created_at: datetime
    expires_at: datetime
    sender: PeerIdentity
    recipient_peer_id: str
    kind: Kind
    content: str
    reply_to: str | None = None
    conversation_id: str | None = None
    hop_count: int = 0

    def __post_init__(self) -> None:
        if self.protocol not in (PROTOCOL_ID, PROTOCOL_ID_V2):
            raise ValidationError(
                f"unsupported protocol {self.protocol!r}; expected {PROTOCOL_ID} or {PROTOCOL_ID_V2}"
            )
        object.__setattr__(self, "message_id", _require_uuid("message_id", self.message_id))
        created = _require_utc_datetime("created_at", self.created_at)
        expires = _require_utc_datetime("expires_at", self.expires_at)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        if expires <= created:
            raise ValidationError("expires_at must be after created_at")
        if not isinstance(self.sender, PeerIdentity):
            raise ValidationError("sender must be a PeerIdentity")
        object.__setattr__(self, "recipient_peer_id", _require_uuid("recipient_peer_id", self.recipient_peer_id))
        if not isinstance(self.kind, Kind):
            if isinstance(self.kind, str):
                try:
                    object.__setattr__(self, "kind", Kind(self.kind))
                except ValueError:
                    raise ValidationError(f"unknown kind {self.kind!r}") from None
            else:
                raise ValidationError("kind must be a Kind")
        if not isinstance(self.content, str):
            raise ValidationError("content must be a string")
        content_bytes = len(self.content.encode("utf-8"))
        if content_bytes > MAX_CONTENT_BYTES:
            raise ValidationError(
                f"content exceeds {MAX_CONTENT_BYTES} bytes ({content_bytes} bytes)"
            )
        if self.reply_to is not None:
            object.__setattr__(self, "reply_to", _require_uuid("reply_to", self.reply_to))
        if self.conversation_id is not None and not isinstance(self.conversation_id, str):
            raise ValidationError("conversation_id must be a string or None")
        if not isinstance(self.hop_count, int) or isinstance(self.hop_count, bool):
            raise ValidationError("hop_count must be an integer")
        if self.hop_count < 0 or self.hop_count > MAX_HOP_COUNT:
            raise ValidationError(f"hop_count {self.hop_count} outside 0..{MAX_HOP_COUNT}")

    def is_expired(self, now: datetime | None = None) -> bool:
        """True when the envelope has passed its expiry."""
        return self.expires_at <= (now or datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Receipt:
    """Immediate delivery receipt returned to the sender."""

    message_id: str
    state: ReceiptState
    recipient_peer_id: str
    detail: str = ""
    delivered_at: str = ""  # RFC3339 UTC

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _require_uuid("message_id", self.message_id))
        object.__setattr__(self, "recipient_peer_id", _require_uuid("recipient_peer_id", self.recipient_peer_id))
        if not isinstance(self.state, ReceiptState):
            raise ValidationError("state must be a ReceiptState")

    def as_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "state": self.state.value,
            "recipient_peer_id": self.recipient_peer_id,
            "detail": self.detail,
            "delivered_at": self.delivered_at,
        }


def make_envelope(
    *,
    message_id: str | None = None,
    sender: PeerIdentity,
    recipient_peer_id: str,
    kind: Kind = Kind.MESSAGE,
    content: str,
    reply_to: str | None = None,
    conversation_id: str | None = None,
    hop_count: int = 0,
    ttl_seconds: float = 300,
    now: datetime | None = None,
) -> Envelope:
    """Construct a validated envelope with defaults filled in."""
    now = now or datetime.now(UTC)
    return Envelope(
        protocol=PROTOCOL_ID,
        message_id=message_id or str(uuidlib.uuid4()),
        created_at=now,
        expires_at=now + timedelta_seconds(ttl_seconds),
        sender=sender,
        recipient_peer_id=recipient_peer_id,
        kind=kind,
        content=content,
        reply_to=reply_to,
        conversation_id=conversation_id,
        hop_count=hop_count,
    )


def timedelta_seconds(seconds: float):
    from datetime import timedelta

    return timedelta(seconds=seconds)


__all__ = [
    "Envelope",
    "Kind",
    "PeerIdentity",
    "PeerRecord",
    "Policy",
    "Presence",
    "Receipt",
    "ReceiptState",
    "Surface",
    "make_envelope",
]
