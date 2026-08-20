"""Presence helpers: bounded heartbeat cadence and status transitions (AP-405).

Heartbeats are hints — socket handshakes remain authoritative (AP-406).
"""

from __future__ import annotations

import logging
import time

from .constants import HEARTBEAT_INTERVAL, STALE_THRESHOLD
from .models import Presence
from .registry import Registry

logger = logging.getLogger("agent_peer.presence")


class PresenceManager:
    """Owns one peer's presence state and bounded heartbeat writes.

    ``heartbeat()`` writes at most once per interval (bounded writes);
    ``mark_*`` helpers map session lifecycle to presence states.
    """

    def __init__(self, registry: Registry, peer_id: str, interval: float = HEARTBEAT_INTERVAL) -> None:
        self._registry = registry
        self._peer_id = peer_id
        self._interval = interval
        self._last_write = float("-inf")  # first heartbeat is always due
        self._status = Presence.IDLE

    def heartbeat(self, force: bool = False) -> bool:
        """Write a heartbeat only when due. Returns True when written."""
        now = time.monotonic()
        if not force and (now - self._last_write) < self._interval:
            return False
        self._registry.heartbeat(self._peer_id)
        self._last_write = now
        return True

    def set_status(self, status: Presence, *, activity: str | None = None) -> None:
        if status is self._status and activity is None:
            return
        # R4: authority-fenced write. Fetch the CURRENT bound record and pass
        # it as `expected` so a stale writer (e.g. after a session reset)
        # cannot clobber a replacement record's status/activity. The fence
        # returns None when the record changed under us — don't update our
        # in-memory state in that case.
        record = self._registry.get(self._peer_id)
        updated = self._registry.update_presence(
            self._peer_id, status, current_activity=activity, expected=record
        )
        if updated is None:
            logger.debug("hermes-peer: presence write rejected by authority fence for %s", self._peer_id)
            return
        self._status = status
        self._last_write = time.monotonic()

    @property
    def status(self) -> Presence:
        return self._status

    def mark_working(self, activity: str | None = None) -> None:
        self.set_status(Presence.WORKING, activity=activity)

    def mark_idle(self, activity: str | None = None) -> None:
        self.set_status(Presence.IDLE, activity=activity)

    def mark_closing(self) -> None:
        self.set_status(Presence.CLOSING)


def stale_after() -> float:
    """Seconds after which a peer without heartbeats is a stale candidate."""
    return STALE_THRESHOLD
