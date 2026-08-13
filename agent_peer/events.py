"""Bounded local event broker (P6.4, G1.8).

Local peer/presence/message/group/request transitions, pushed to bounded
clients. Subscribers are retained; each client keeps a bounded buffer and
the OLDEST buffered events are dropped when a slow consumer falls behind —
event load must never block or fail message delivery (P6 gate). No
persistence; the store is the durable record.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any


class EventBroker:
    """Thread-safe fan-out of local events to bounded subscribers."""

    def __init__(self, *, client_capacity: int = 100, max_clients: int = 32) -> None:
        self._lock = threading.Lock()
        self._client_capacity = client_capacity
        self._max_clients = max_clients
        self._subscribers: dict[int, deque[dict]] = {}
        self._next_id = 1

    def subscribe(self) -> int:
        """Register a client; returns an opaque subscription id (bounded)."""
        with self._lock:
            if len(self._subscribers) >= self._max_clients:
                raise OverflowError("event broker client cap reached")
            sid = self._next_id
            self._next_id += 1
            self._subscribers[sid] = deque(maxlen=self._client_capacity)
            return sid

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subscribers.pop(sid, None)

    def publish(self, kind: str, **fields: Any) -> None:
        """Publish one event. Never raises on a slow/dropped consumer."""
        event = {"kind": kind, **fields}
        with self._lock:
            for _sid, queue in list(self._subscribers.items()):
                queue.append(event)

    def drain(self, sid: int) -> list[dict]:
        """Pop all buffered events for one client (FIFO)."""
        with self._lock:
            queue = self._subscribers.get(sid)
            if queue is None:
                return []
            return [queue.popleft() for _ in range(len(queue))]

    def client_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def close(self) -> None:
        with self._lock:
            self._subscribers.clear()


__all__ = ["EventBroker"]
