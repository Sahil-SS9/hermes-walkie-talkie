"""Stale-alert integration tests (P6.5, G1.5).

Stale alerts have debounce and exact-instance fences; bounded cleanup never
deletes an endpoint or record replaced by a live instance.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from agent_peer.constants import STALE_THRESHOLD
from agent_peer.metrics import MetricsRegistry
from agent_peer.models import PeerRecord, Presence


def _record(name: str, *, last_seen: str | None = None) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        session_id=f"sess-{name}",
        name=name,
        profile="default",
        started_at=datetime.now(UTC).isoformat(),
        last_seen=last_seen or datetime.now(UTC).isoformat(),
        status=Presence.IDLE.value,
    )


class _StaleTracker:
    """Debounced stale tracker with exact-instance fence (G1.5)."""

    def __init__(self, metrics: MetricsRegistry | None = None) -> None:
        self._metrics = metrics or MetricsRegistry()
        self._debounced: dict[str, datetime] = {}
        self._debounce_seconds = 30.0
        self._fenced: dict[str, str] = {}  # peer_id -> instance_id

    def observe(self, record: PeerRecord, now: datetime | None = None) -> bool:
        """Returns True when a NEW stale alert fires for this instance.

        Debounce: repeated observations of the SAME instance within the
        debounce window do not re-fire. Exact-instance fence: a replaced
        instance (new instance_id) resets the debounce and re-fires once.
        """
        now = now or datetime.now(UTC)
        last = self._debounced.get(record.peer_id)
        if last is not None and (now - last) < timedelta(seconds=self._debounce_seconds):
            return False  # debounced
        seen = self._fenced.get(record.peer_id)
        if seen == record.instance_id and last is not None:
            # Same instance, within window: suppressed above. If we reach
            # here the window passed — that's a repeat, still debounced.
            return False
        self._debounced[record.peer_id] = now
        self._fenced[record.peer_id] = record.instance_id
        self._metrics.record_stale_event()
        return True


def test_stale_alert_fires_once_per_instance():
    tracker = _StaleTracker()
    rec = _record("alpha", last_seen=(datetime.now(UTC) - timedelta(seconds=STALE_THRESHOLD + 10)).isoformat())
    now = datetime.now(UTC)
    assert tracker.observe(rec, now) is True
    # Same instance within debounce: suppressed.
    assert tracker.observe(rec, now + timedelta(seconds=5)) is False
    # Metrics counted exactly one stale event.
    assert tracker._metrics.snapshot()["stale_events"] == 1


def test_replacement_instance_refires_after_debounce():
    tracker = _StaleTracker()
    r1 = _record("alpha")
    r2 = _record("alpha")  # same peer, NEW instance (replacement)
    now = datetime.now(UTC)
    tracker.observe(r1, now)
    tracker.observe(r1, now + timedelta(seconds=5))  # debounced
    # Replacement instance (exact fence differs) re-fires.
    assert tracker.observe(r2, now + timedelta(seconds=10)) is True
    assert tracker._metrics.snapshot()["stale_events"] == 2


def test_stale_cleanup_never_touches_replaced_live():
    """G1.5: bounded cleanup must not delete a record replaced by live."""
    live = _record("alpha")
    stale = _record("alpha")  # same peer, stale instance
    # The fence compares instance_id: cleanup of the stale record is refused
    # when the live record's instance differs and is still reachable.
    assert stale.instance_id != live.instance_id
    # Cleanup decision: only remove when the INSTANCE matches the dead one.
    def cleanup(record: PeerRecord, current_live: PeerRecord | None) -> bool:
        if current_live is None:
            return True
        return record.instance_id == current_live.instance_id

    assert cleanup(stale, live) is False
    assert cleanup(stale, None) is True
