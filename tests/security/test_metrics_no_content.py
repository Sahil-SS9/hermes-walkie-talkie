"""Metrics no-content security tests (P6.2, G1.2/G1.3)."""

from __future__ import annotations

import json

import agent_peer.metrics
from agent_peer.metrics import MetricsRegistry


def test_metrics_module_has_no_content_fields():
    """Structural gate: metrics recorders take no content-bearing params.

    The module docstring may mention 'content' in prose; the hard property
    is that no recording function accepts a payload, text, body or secret.
    """
    import inspect as _inspect

    for name in ("record_delivery", "record_held", "record_stale_event", "record_request_state"):
        fn = getattr(agent_peer.metrics.MetricsRegistry, name)
        sig = _inspect.signature(fn)
        params = " ".join(sig.parameters)
        for forbidden in ("content", "text", "body", "payload", "prompt", "secret", "token", "message"):
            assert forbidden not in params, f"{name} accepts content-bearing param {forbidden!r}"


def test_snapshot_is_json_serializable_and_content_free():
    m = MetricsRegistry()
    m.record_delivery(sent=True, latency_ms=2.5)
    m.record_delivery(sent=False, reason="unreachable")
    m.record_held(1)
    m.record_request_state("accepted")
    text = json.dumps(m.snapshot())
    # Round-trips and contains no free-text payload.
    assert json.loads(text)["delivered"] == 1
    for forbidden in ("summary", "detail", "instruction", "say", "write"):
        assert forbidden not in text.lower()


def test_failure_reason_is_enum_like_bounded():
    """Failure reasons are bounded state names, not free-form content."""
    m = MetricsRegistry()
    m.record_delivery(sent=False, reason="unreachable")
    m.record_delivery(sent=False, reason="refused")
    reasons = m.snapshot()["failure_reasons"]
    assert set(reasons) == {"unreachable", "refused"}
