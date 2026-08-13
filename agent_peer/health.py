"""Health snapshot (P6.3, G1.4): backend, registry, peers, store, groups,
requests and stale state — with actionable remedies. Content-free.
"""

from __future__ import annotations

import logging
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from .constants import STALE_THRESHOLD

logger = logging.getLogger("agent_peer.health")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def health_snapshot(
    *,
    backend_kind: str,
    runtime_dir: Path,
    registry_entries: int,
    local_sessions: int,
    live_peers: int,
    pending_messages: int,
    groups: int,
    active_requests: int,
    stale_count: int,
    store_ok: bool = True,
    metrics: dict | None = None,
) -> dict:
    """Build the content-free health snapshot with actionable remedies.

    Every degradation carries a ``remedy`` string so doctor/status output
    can tell the user what to do next (G1.4).
    """
    now = _now_iso()
    problems: list[dict] = []
    runtime_dir = Path(runtime_dir)

    if not runtime_dir.exists():
        problems.append(
            {"key": "runtime_dir_missing", "severity": "error", "remedy": "re-run the plugin to recreate the owner-local runtime root"}
        )
    elif runtime_dir.is_symlink():
        problems.append(
            {"key": "runtime_dir_symlink", "severity": "error", "remedy": "remove the symlink; the runtime root must be a real owner-only directory"}
        )
    if stale_count > 0:
        problems.append(
            {
                "key": "stale_peers",
                "severity": "warning",
                "remedy": f"run `hermes peer doctor --repair` (bounded cleanup; never deletes a replaced live instance) ({stale_count} stale)",
            }
        )
    if pending_messages > 0:
        problems.append(
            {
                "key": "pending_messages",
                "severity": "info",
                "remedy": f"{pending_messages} held/queued messages; read the inbox or release/refuse held items",
            }
        )
    if not store_ok:
        problems.append(
            {"key": "store_unavailable", "severity": "error", "remedy": "check the owner-local state dir is writable and not full"}
        )

    return {
        "timestamp": now,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "backend": backend_kind,
        "runtime_dir": str(runtime_dir),
        "registry_entries": registry_entries,
        "local_sessions": local_sessions,
        "live_peers": live_peers,
        "pending_messages": pending_messages,
        "groups": groups,
        "active_requests": active_requests,
        "stale_count": stale_count,
        "store_ok": store_ok,
        "stale_threshold_seconds": STALE_THRESHOLD,
        "metrics": metrics or {},
        "problems": problems,
        "ok": not any(p["severity"] == "error" for p in problems),
    }


__all__ = ["health_snapshot"]
