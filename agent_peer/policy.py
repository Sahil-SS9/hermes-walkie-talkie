"""Inbound policies, rate/capacity limits and delivery decisions (AP-604..AP-609, AP-612).

The :class:`PolicyEngine` evaluates one incoming envelope and returns a
:class:`DeliveryDecision`:

- ``(queued, forward)`` — accept policy; the host forwards to the harness
  and only then is the receipt ``queued``.
- ``(held, hold)`` — hold policy; persisted without forwarding; explicit
  release/refuse actions are exposed.
- ``(refused, refuse)`` — refuse policy; minimal audit metadata only.
- ``(expired|rate_limited|over_capacity|invalid, drop)`` — never reaches
  the harness; the sender gets the explicit non-success receipt.

Rate limiting: burst + sustained per sender/recipient pair. Capacity: the
recipient's pending inbox (queued + held) is bounded.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .constants import (
    INBOX_CAPACITY,
    MAX_HOP_COUNT,
    RATE_BURST,
    RATE_SUSTAINED,
    RATE_WINDOW_SECONDS,
)
from .models import Envelope, Policy, ReceiptState


@dataclass(frozen=True, slots=True)
class DeliveryDecision:
    """Outcome of evaluating one inbound envelope."""

    message_id: str
    state: ReceiptState
    action: str  # forward | hold | refuse | drop
    conversation_id: str | None = None


class RateLimiter:
    """Sliding-window rate limit per (sender, recipient) pair.

    Burst: at most ``burst`` messages accepted at once. Sustained: at most
    ``sustained_per_minute`` per 60-second window.
    """

    def __init__(self, burst: int = RATE_BURST, sustained_per_minute: int = RATE_SUSTAINED, window_seconds: float = RATE_WINDOW_SECONDS) -> None:
        self._burst = burst
        self._sustained = sustained_per_minute
        self._window = window_seconds
        self._events: dict[tuple[str, str], deque] = {}

    def allow(self, sender: str, recipient: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        key = (sender, recipient)
        events = self._events.setdefault(key, deque())
        while events and events[0] <= now - self._window:
            events.popleft()
        if len(events) >= self._sustained:
            return False
        if len(events) >= self._burst and events and (now - events[0]) < 1.0:
            # Burst gate: more than `burst` arrivals within one second are
            # refused even if the window has room.
            return False
        events.append(now)
        return True


class PolicyEngine:
    """Evaluates inbound envelopes against policy, rate, capacity and TTL."""

    def __init__(
        self,
        policy: Policy | str = Policy.ACCEPT,
        *,
        rate_burst: int = RATE_BURST,
        rate_per_minute: int = RATE_SUSTAINED,
        capacity: int = INBOX_CAPACITY,
        max_hop_count: int = MAX_HOP_COUNT,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.set_policy(policy)
        self._limiter = limiter or RateLimiter(burst=rate_burst, sustained_per_minute=rate_per_minute)
        self._capacity = capacity
        self._max_hop_count = max_hop_count
        # Recipient -> pending count (maintained by the caller via
        # register_pending/release; defaults to zero for pure decisions).
        self._pending: dict[str, int] = {}

    def set_policy(self, policy: Policy | str) -> None:
        self._policy = policy if isinstance(policy, Policy) else Policy(policy)

    @property
    def policy(self) -> Policy:
        return self._policy

    def register_pending(self, recipient: str, count: int) -> None:
        self._pending[recipient] = count

    def release(self, message_id: str) -> bool:
        """Explicit release action for a held message (host resolves target)."""
        return True

    def refuse(self, message_id: str) -> bool:
        """Explicit refuse action for a held message (host resolves target)."""
        return True

    def evaluate(self, envelope: Envelope, now: datetime | None = None) -> DeliveryDecision:
        """Decide the fate of one inbound envelope (never raises)."""
        if envelope.is_expired(now):
            return DeliveryDecision(envelope.message_id, ReceiptState.EXPIRED, "drop", envelope.conversation_id)
        if envelope.hop_count >= self._max_hop_count:
            return DeliveryDecision(envelope.message_id, ReceiptState.INVALID, "drop", envelope.conversation_id)
        if not self._limiter.allow(envelope.sender.peer_id, envelope.recipient_peer_id):
            return DeliveryDecision(envelope.message_id, ReceiptState.RATE_LIMITED, "drop", envelope.conversation_id)
        pending = self._pending.get(envelope.recipient_peer_id, 0)
        if pending >= self._capacity:
            return DeliveryDecision(envelope.message_id, ReceiptState.OVER_CAPACITY, "drop", envelope.conversation_id)

        if self._policy is Policy.HOLD:
            return DeliveryDecision(envelope.message_id, ReceiptState.HELD, "hold", envelope.conversation_id)
        if self._policy is Policy.REFUSE:
            return DeliveryDecision(envelope.message_id, ReceiptState.REFUSED, "refuse", envelope.conversation_id)
        return DeliveryDecision(envelope.message_id, ReceiptState.QUEUED, "forward", envelope.conversation_id)
