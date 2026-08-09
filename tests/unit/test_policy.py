"""RED tests for inbound policies, receipts, TTL, rate/capacity limits (AP-604..AP-609, AP-612)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.models import Envelope, Kind, PeerIdentity, Policy, ReceiptState
from agent_peer.policy import PolicyEngine, RateLimiter

NOW = datetime.now(UTC)


def _identity() -> PeerIdentity:
    return PeerIdentity(peer_id=str(uuid.uuid4()), name="tester", profile="test")


def _env(sender: PeerIdentity | None = None, recipient: str | None = None, **kw) -> Envelope:
    return Envelope(
        protocol="agent-peer/1",
        message_id=kw.pop("message_id", str(uuid.uuid4())),
        created_at=kw.pop("created_at", NOW),
        expires_at=kw.pop("expires_at", NOW + timedelta(minutes=5)),
        sender=sender or _identity(),
        recipient_peer_id=recipient or str(uuid.uuid4()),
        kind=kw.pop("kind", Kind.MESSAGE),
        content=kw.pop("content", "hello"),
        reply_to=kw.pop("reply_to", None),
        conversation_id=kw.pop("conversation_id", None),
        hop_count=kw.pop("hop_count", 0),
    )


class TestRateLimiter:
    def test_burst_limit(self):
        limiter = RateLimiter(burst=5, sustained_per_minute=20)
        sender = str(uuid.uuid4())
        recipient = str(uuid.uuid4())
        for _ in range(5):
            assert limiter.allow(sender, recipient) is True
        assert limiter.allow(sender, recipient) is False  # burst exhausted

    def test_sustained_rate_over_window(self):
        limiter = RateLimiter(burst=5, sustained_per_minute=20)
        sender = str(uuid.uuid4())
        recipient = str(uuid.uuid4())
        # A long-running trickle: 20 events at t=0,3,...,57s.
        now = time.monotonic()
        for i in range(20):
            assert limiter.allow(sender, recipient, now=now + i * 3.0) is True
        # At t=59 nothing has expired: still refused.
        assert limiter.allow(sender, recipient, now=now + 59.0) is False
        # At t=61 the two oldest events (t=0, t=3) have expired: allowed.
        assert limiter.allow(sender, recipient, now=now + 61.0) is True

    def test_old_events_expire(self):
        limiter = RateLimiter(burst=2, sustained_per_minute=10)
        sender = str(uuid.uuid4())
        recipient = str(uuid.uuid4())
        now = time.monotonic()
        assert limiter.allow(sender, recipient, now=now) is True
        assert limiter.allow(sender, recipient, now=now) is True
        assert limiter.allow(sender, recipient, now=now) is False
        # After the window, capacity returns.
        assert limiter.allow(sender, recipient, now=now + 61) is True

    def test_pairs_are_independent(self):
        limiter = RateLimiter(burst=1, sustained_per_minute=5)
        a1, a2 = str(uuid.uuid4()), str(uuid.uuid4())
        b = str(uuid.uuid4())
        assert limiter.allow(a1, b) is True
        assert limiter.allow(a1, b) is False
        assert limiter.allow(a2, b) is True  # different sender unaffected


class TestPolicyEngine:
    def test_accept_policy_forwards(self):
        engine = PolicyEngine(policy=Policy.ACCEPT)
        decision = engine.evaluate(_env())
        assert decision.state is ReceiptState.QUEUED
        assert decision.action == "forward"

    def test_hold_policy_holds(self):
        engine = PolicyEngine(policy=Policy.HOLD)
        decision = engine.evaluate(_env())
        assert decision.state is ReceiptState.HELD
        assert decision.action == "hold"

    def test_refuse_policy_refuses(self):
        engine = PolicyEngine(policy=Policy.REFUSE)
        decision = engine.evaluate(_env())
        assert decision.state is ReceiptState.REFUSED
        assert decision.action == "refuse"

    def test_expired_never_reaches_harness(self):
        engine = PolicyEngine(policy=Policy.ACCEPT)
        # Valid at construction (expires > created) but already expired
        # relative to the evaluation clock — the wire-expiry case.
        env = _env(created_at=NOW - timedelta(minutes=10), expires_at=NOW - timedelta(minutes=5))
        decision = engine.evaluate(env)
        assert decision.state is ReceiptState.EXPIRED
        assert decision.action == "drop"

    def test_hop_cap_rejected(self):
        engine = PolicyEngine(policy=Policy.ACCEPT)
        env = _env(hop_count=4)
        decision = engine.evaluate(env)
        assert decision.state is ReceiptState.INVALID
        assert decision.action == "drop"

    def test_rate_limited_receipt(self):
        engine = PolicyEngine(policy=Policy.ACCEPT, rate_burst=1, rate_per_minute=5)
        sender = _identity()
        recipient = str(uuid.uuid4())
        assert engine.evaluate(_env(sender=sender, recipient=recipient)).action == "forward"
        decision = engine.evaluate(_env(sender=sender, recipient=recipient))
        assert decision.state is ReceiptState.RATE_LIMITED
        assert decision.action == "drop"

    def test_over_capacity_receipt(self):
        engine = PolicyEngine(policy=Policy.ACCEPT, capacity=2)
        recipient = str(uuid.uuid4())
        engine.register_pending(recipient, 0)
        for _ in range(2):
            assert engine.evaluate(_env(recipient=recipient)).action == "forward"
        # Host reports the inbox is full (store.count_pending feeds this).
        engine.register_pending(recipient, 2)
        decision = engine.evaluate(_env(recipient=recipient))
        assert decision.state is ReceiptState.OVER_CAPACITY
        assert decision.action == "drop"

    def test_hold_release_flow(self):
        """AP-605: hold persists; release/refuse actions are exposed."""
        engine = PolicyEngine(policy=Policy.HOLD)
        env = _env()
        decision = engine.evaluate(env)
        assert decision.state is ReceiptState.HELD
        # Explicit release of a held message flips it to forwardable.
        assert engine.release(env.message_id) is True
        assert engine.refuse(env.message_id) is True

    def test_reply_correlation_preserved(self):
        """AP-607: reply_to is validated and conversation_id preserved."""
        engine = PolicyEngine(policy=Policy.ACCEPT)
        original = _env(conversation_id="conv-9")
        reply = _env(reply_to=original.message_id, conversation_id="conv-9")
        decision = engine.evaluate(reply)
        assert decision.action == "forward"
        assert reply.reply_to == original.message_id
        assert reply.conversation_id == "conv-9"

    def test_reply_to_invalid_uuid_rejected_at_model(self):
        from agent_peer.errors import ValidationError

        with pytest.raises(ValidationError):
            _env(reply_to="not-a-uuid")

    def test_policy_change_takes_effect(self):
        engine = PolicyEngine(policy=Policy.ACCEPT)
        assert engine.evaluate(_env()).action == "forward"
        engine.set_policy(Policy.REFUSE)
        assert engine.evaluate(_env()).action == "refuse"


class TestIdempotencyProperties:
    def test_retries_do_not_amplify(self):
        """AP-612: retrying the same message yields consistent outcomes;
        one-delivery-per-message-id is enforced by the store (see test_store)."""
        engine = PolicyEngine(policy=Policy.ACCEPT, rate_burst=100, rate_per_minute=1000)
        env = _env()
        first = engine.evaluate(env)
        for _ in range(5):
            again = engine.evaluate(env)
            assert again.message_id == first.message_id
            assert again.state is first.state
            assert again.action == first.action

    def test_no_reply_leakage_across_peers(self):
        engine = PolicyEngine(policy=Policy.ACCEPT)
        reply_a = _env(reply_to=str(uuid.uuid4()), conversation_id="conv-A")
        reply_b = _env(reply_to=str(uuid.uuid4()), conversation_id="conv-B")
        da = engine.evaluate(reply_a)
        db = engine.evaluate(reply_b)
        assert da.conversation_id == "conv-A"
        assert db.conversation_id == "conv-B"
        assert da.state is db.state
