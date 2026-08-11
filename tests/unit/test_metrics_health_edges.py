"""Metrics + health edge branches (P11.1 coverage).

- Metrics: negative latency and empty reason take the alternate branches
  of record_delivery.
- Health: a symlinked runtime dir and zero pending messages exercise the
  remaining branches.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_peer.health import health_snapshot
from agent_peer.metrics import MetricsRegistry


class TestMetricsEdgeBranches:
    def test_record_delivery_negative_latency_no_reason(self):
        m = MetricsRegistry(max_latency_samples=10)
        m.record_delivery(sent=True, latency_ms=-1)  # negative: no latency sample
        m.record_delivery(sent=False, reason="")  # no reason: no failure-reason row
        snap = m.snapshot()
        assert snap["delivered"] == 1
        assert snap["failed"] == 1
        assert snap["latency_ms"]["samples"] == 0  # negative latency not sampled
        assert snap["failure_reasons"] == {}

    def test_record_delivery_positive_path(self):
        m = MetricsRegistry(max_latency_samples=10)
        m.record_delivery(sent=True, latency_ms=12.5)
        m.record_delivery(sent=False, reason="rate_limited")
        snap = m.snapshot()
        assert snap["failure_reasons"] == {"rate_limited": 1}

    def test_record_held_and_request_state(self):
        m = MetricsRegistry(max_latency_samples=10)
        m.record_held(3)
        m.record_stale_event()
        m.record_request_state("accepted")
        snap = m.snapshot()
        assert snap["held_depth"] == 3
        assert snap["stale_events"] == 1
        assert snap["request_states"] == {"accepted": 1}


class TestHealthEdgeBranches:
    def test_symlinked_runtime_dir_problem(self):
        base = Path(tempfile.mkdtemp())
        real = base / "real"
        real.mkdir()
        link = base / "link"
        link.symlink_to(real, target_is_directory=True)
        snap = health_snapshot(
            runtime_dir=str(link),
            registry_entries=0,
            local_sessions=0,
            live_peers=0,
            pending_messages=0,
            stale_count=0,
            store_ok=True,
            backend_kind="posix",
            groups=0,
            active_requests=0,
        )
        keys = {p["key"] for p in snap["problems"]}
        assert "runtime_dir_symlink" in keys

    def test_no_pending_no_stale_clean(self):
        snap = health_snapshot(
            runtime_dir=str(Path(tempfile.mkdtemp())),
            registry_entries=1,
            local_sessions=1,
            live_peers=1,
            pending_messages=0,
            stale_count=0,
            store_ok=True,
            backend_kind="posix",
            groups=0,
            active_requests=0,
        )
        assert snap["problems"] == []
        assert snap["backend"] == "posix"
