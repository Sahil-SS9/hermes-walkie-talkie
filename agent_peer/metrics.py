"""Owner-local delivery metrics (P6.1/P6.2, G1.1..G1.3).

Counts, latency, failure reason, queue/hold depth and stale-peer events —
NEVER content, prompts, credentials or message bodies (G1.2). No outbound
telemetry; everything stays in-process and owner-local (G1.3). Latency
samples are bounded; counters are not (retention policy P6.1).
"""

from __future__ import annotations

import threading
import time
from collections import Counter, deque


class MetricsRegistry:
    """Thread-safe in-memory metrics, content-free by construction."""

    def __init__(self, *, max_latency_samples: int = 500) -> None:
        self._lock = threading.Lock()
        self._max_samples = max_latency_samples
        self._started_at = time.time()
        self._delivered = 0
        self._failed = 0
        self._failure_reasons: Counter[str] = Counter()
        self._latencies: deque[float] = deque(maxlen=max_latency_samples)
        self._held_depth = 0
        self._stale_events = 0
        self._request_states: Counter[str] = Counter()

    def record_delivery(self, *, sent: bool, latency_ms: float = 0.0, reason: str = "") -> None:
        with self._lock:
            if sent:
                self._delivered += 1
                if latency_ms >= 0:
                    self._latencies.append(latency_ms)
            else:
                self._failed += 1
                if reason:
                    self._failure_reasons[reason] += 1

    def record_held(self, depth: int) -> None:
        with self._lock:
            self._held_depth = depth

    def record_stale_event(self) -> None:
        with self._lock:
            self._stale_events += 1

    def record_request_state(self, state: str) -> None:
        with self._lock:
            self._request_states[state] += 1

    def snapshot(self) -> dict:
        """Bounded, content-free snapshot for doctor/status/desktop."""
        with self._lock:
            lat = sorted(self._latencies)
            p50 = lat[len(lat) // 2] if lat else 0.0
            p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0.0
            return {
                "started_at": self._started_at,
                "delivered": self._delivered,
                "failed": self._failed,
                "failure_reasons": dict(self._failure_reasons),
                "latency_ms": {"p50": round(p50, 2), "p95": round(p95, 2), "samples": len(lat)},
                "held_depth": self._held_depth,
                "stale_events": self._stale_events,
                "request_states": dict(self._request_states),
            }


__all__ = ["MetricsRegistry"]
