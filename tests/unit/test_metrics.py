"""Local metrics tests (P6.1/P6.2, G1.1..G1.3).

Metrics carry counts, latency, failure reason, queue/hold depth and
stale-peer events ONLY — never content, prompts, credentials or message
bodies (G1.2). All data stays owner-local; no outbound telemetry (G1.3).
"""

from __future__ import annotations

import json

from agent_peer.metrics import MetricsRegistry


def test_record_and_read_counts():
    m = MetricsRegistry()
    m.record_delivery(sent=True, latency_ms=5.0)
    m.record_delivery(sent=True, latency_ms=7.0)
    m.record_delivery(sent=False, reason="unreachable")
    snapshot = m.snapshot()
    assert snapshot["delivered"] == 2
    assert snapshot["failed"] == 1
    assert snapshot["failure_reasons"]["unreachable"] == 1
    assert 5.0 <= snapshot["latency_ms"]["p50"] <= 7.0


def test_metrics_record_structural_shapes():
    m = MetricsRegistry()
    m.record_delivery(sent=False, reason="refused")
    m.record_held(3)
    m.record_stale_event()
    m.record_request_state("completed")
    snap = m.snapshot()
    # Keys are bounded and content-free.
    assert set(snap) <= {
        "delivered", "failed", "failure_reasons", "latency_ms",
        "held_depth", "stale_events", "request_states", "started_at",
    }
    assert snap["held_depth"] == 3
    assert snap["stale_events"] == 1
    assert snap["request_states"]["completed"] == 1


def test_metrics_never_contain_content():
    """G1.2 structural guard: no message/request body may enter metrics."""
    m = MetricsRegistry()
    m.record_delivery(sent=True, latency_ms=1.0)
    payload = json.dumps(m.snapshot())
    for forbidden in ("message_id", "content", "prompt", "secret", "credentials", "body", "text"):
        assert forbidden not in payload.lower()


def test_retention_bounded():
    m = MetricsRegistry(max_latency_samples=5)
    for _ in range(20):
        m.record_delivery(sent=True, latency_ms=1.0)
    assert len(m._latencies) <= 5
    assert m.snapshot()["delivered"] == 20  # counters unbounded, samples bounded


def test_metrics_are_local_no_telemetry():
    """G1.3: no outbound hook; the registry is a plain in-memory object."""
    m = MetricsRegistry()
    assert not hasattr(m, "send")
    assert not hasattr(m, "flush")
    assert not hasattr(m, "export")
