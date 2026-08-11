"""Request store idempotency + state tests (P5.2, P5.4, P5.7, P5.8, G4.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.requests import RequestStore
from agent_peer.store import MessageStore


@pytest.fixture()
def rstore(tmp_path):
    store = MessageStore(tmp_path / "messages.sqlite3")
    rs = RequestStore(store)
    yield rs
    store.close()


def _deadline(offset_minutes: int = 10) -> str:
    return (datetime.now(UTC) + timedelta(minutes=offset_minutes)).isoformat()


def _create(rstore, **overrides):
    base = dict(
        sender_agent_id="sender-a",
        recipient_agent_id="recipient-b",
        summary="please do X",
        deadline=_deadline(),
    )
    base.update(overrides)
    return rstore.create(**base)


def test_create_and_get(rstore):
    r = _create(rstore)
    assert r.state == "created"
    got = rstore.get(r.request_id)
    assert got is not None
    assert got.summary == "please do X"
    assert got.sender_agent_id == "sender-a"


def test_idempotency_key_returns_original(rstore):
    """G4.7: repeated key from the same sender returns the original request."""
    key = "op-123"
    first = _create(rstore, idempotency_key=key)
    second = _create(rstore, idempotency_key=key)
    assert first.request_id == second.request_id
    # The state is the ORIGINAL (still created), never duplicated work.
    assert second.state == "created"
    with rstore._store._lock:
        n = rstore._conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    assert n == 1


def test_same_key_different_sender_allowed(rstore):
    key = "shared-key"
    a = _create(rstore, sender_agent_id="sender-a", idempotency_key=key)
    b = _create(rstore, sender_agent_id="sender-c", idempotency_key=key)
    assert a.request_id != b.request_id


def test_full_workflow_through_store(rstore):
    r = _create(rstore)
    rstore.transition(r.request_id, "queued")
    rstore.transition(r.request_id, "accepted")
    rstore.transition(r.request_id, "in_progress", detail="started")
    rstore.transition(r.request_id, "completed", detail="done")
    final = rstore.get(r.request_id)
    assert final.state == "completed"
    events = rstore.events(r.request_id)
    states = [e.state for e in events]
    assert states == ["created", "queued", "accepted", "in_progress", "completed"]
    assert events[-1].detail == "done"


def test_impossible_transition_is_noop(rstore):
    r = _create(rstore)
    # queued -> completed is impossible (must accept first).
    rstore.transition(r.request_id, "queued")
    after = rstore.transition(r.request_id, "completed")
    assert after.state == "queued"


def test_terminal_state_frozen(rstore):
    r = _create(rstore)
    rstore.transition(r.request_id, "queued")
    rstore.transition(r.request_id, "refused")
    after = rstore.transition(r.request_id, "accepted")
    assert after.state == "refused"
    events = rstore.events(r.request_id)
    assert [e.state for e in events] == ["created", "queued", "refused"]


def test_cancel_advisory_from_queued(rstore):
    r = _create(rstore)
    rstore.transition(r.request_id, "queued")
    rstore.transition(r.request_id, "cancelled", detail="no longer needed")
    final = rstore.get(r.request_id)
    assert final.state == "cancelled"


def test_expiry_cleanup(rstore):
    r = _create(rstore, deadline=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())
    expired = rstore.expire_overdue()
    assert expired == 1
    final = rstore.get(r.request_id)
    assert final.state == "expired"


def test_expiry_skips_active_future(rstore):
    r = _create(rstore)  # deadline in the future
    assert rstore.expire_overdue() == 0
    assert rstore.get(r.request_id).state == "created"


def test_list_for_recipient(rstore):
    a = _create(rstore, recipient_agent_id="recip-b", summary="one")
    b = _create(rstore, recipient_agent_id="recip-b", summary="two")
    c = _create(rstore, recipient_agent_id="recip-c", summary="other")
    mine = rstore.list_for_recipient("recip-b")
    assert {x.request_id for x in mine} == {a.request_id, b.request_id}
    assert c.request_id not in {x.request_id for x in mine}
