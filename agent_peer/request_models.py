"""Request models (P5.1, G4.2, ADR-0004).

Typed request aggregate: request_id, sender/recipient (stable agent ids),
state, deadline, idempotency key, correlation, payload and ordered events.
The immediate transport receipt is distinct from workflow state (G4.4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .errors import ValidationError
from .workflows import RequestState


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_request_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class Request:
    request_id: str
    sender_agent_id: str
    recipient_agent_id: str
    state: str
    summary: str
    created_at: str
    deadline: str
    idempotency_key: str = ""
    correlation_id: str = ""
    parent_request_id: str = ""
    payload: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id or not self.sender_agent_id or not self.recipient_agent_id:
            raise ValidationError("request requires request_id, sender and recipient")
        if self.state not in {s.value for s in RequestState}:
            raise ValidationError(f"invalid request state {self.state!r}")

    @property
    def is_expired(self, now: str | None = None) -> bool:
        try:
            deadline = datetime.fromisoformat(self.deadline)
            ref = datetime.fromisoformat(now or _now_iso())
        except ValueError:
            return False
        return ref > deadline


__all__ = ["Request", "new_request_id"]
