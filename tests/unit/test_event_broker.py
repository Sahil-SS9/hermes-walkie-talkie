"""Event broker tests (P6.4, G1.8, P6 gate)."""

from __future__ import annotations

from agent_peer.events import EventBroker


def test_subscribe_publish_drain():
    b = EventBroker()
    sid = b.subscribe()
    b.publish("peer_open", peer_id="p1")
    b.publish("message", peer_id="p2")
    events = b.drain(sid)
    assert [e["kind"] for e in events] == ["peer_open", "message"]
    assert events[0]["peer_id"] == "p1"


def test_publish_never_blocks_delivery():
    """P6 gate: publishing to a full/slow client never raises."""
    b = EventBroker(client_capacity=2)
    sid = b.subscribe()
    for _ in range(10):
        b.publish("noise", i=1)  # must not raise or block
    events = b.drain(sid)
    # Bounded: only the latest 2 remain.
    assert len(events) == 2


def test_client_cap_bounded():
    b = EventBroker(max_clients=2)
    b.subscribe()
    b.subscribe()
    try:
        b.subscribe()
        raise AssertionError("cap should be enforced")
    except OverflowError:
        pass
    assert b.client_count() == 2


def test_unsubscribe_stops_delivery():
    b = EventBroker()
    sid = b.subscribe()
    b.unsubscribe(sid)
    b.publish("x")
    assert b.drain(sid) == []


def test_close_clears_clients():
    b = EventBroker()
    b.subscribe()
    b.close()
    assert b.client_count() == 0
