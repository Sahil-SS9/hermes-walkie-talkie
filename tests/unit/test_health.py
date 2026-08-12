"""Health snapshot tests (P6.3, G1.4)."""

from __future__ import annotations

from agent_peer.health import health_snapshot


def _snap(**overrides):
    base: dict = dict(
        backend_kind="posix",
        runtime_dir="/tmp",
        registry_entries=0,
        local_sessions=0,
        live_peers=0,
        pending_messages=0,
        groups=0,
        active_requests=0,
        stale_count=0,
    )
    base.update(overrides)
    return health_snapshot(**base)


def test_healthy_snapshot(tmp_path):
    snap = _snap(runtime_dir=str(tmp_path))
    assert snap["ok"] is True
    assert snap["backend"] == "posix"
    assert snap["problems"] == []
    assert snap["stale_threshold_seconds"] > 0


def test_stale_peers_problem_with_remedy(tmp_path):
    snap = _snap(runtime_dir=str(tmp_path), stale_count=3)
    assert snap["ok"] is True  # warning, not error
    problems = {p["key"]: p for p in snap["problems"]}
    assert "stale_peers" in problems
    assert "repair" in problems["stale_peers"]["remedy"].lower()


def test_runtime_missing_is_error():
    snap = _snap(runtime_dir="/nonexistent/nope")
    assert snap["ok"] is False
    assert any(p["key"] == "runtime_dir_missing" for p in snap["problems"])


def test_store_unavailable_is_error():
    snap = _snap(store_ok=False)
    assert snap["ok"] is False
    assert any(p["key"] == "store_unavailable" for p in snap["problems"])


def test_metrics_embedded_content_free():
    snap = _snap(metrics={"delivered": 1, "failed": 0})
    assert snap["metrics"]["delivered"] == 1
