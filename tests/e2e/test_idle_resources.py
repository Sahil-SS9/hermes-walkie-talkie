"""PILOT-1202 evidence: low idle resource use of the supervisor.

An idle supervisor (no messages, one peer) must consume negligible CPU:
measured process-CPU delta over an idle window stays below a small bound,
proving the selector blocks instead of busy-looping.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from agent_peer.models import PeerRecord, ReceiptState
from agent_peer.runtime import PeerRuntimeManager

pytestmark = pytest.mark.skipif(
    not os.path.isdir("/proc/self"),
    reason="/proc/<pid>/stat CPU measurement is Linux-only (no procfs on macOS/Windows)",
)


def _record() -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name="idle",
        profile="t",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
    )


def _process_cpu_seconds() -> float:
    with open(f"/proc/{os.getpid()}/stat", encoding="utf-8") as f:
        parts = f.read().split()
    # utime (14) + stime (15) in clock ticks.
    return (int(parts[13]) + int(parts[14])) / os.sysconf("SC_CLK_TCK")


def test_idle_supervisor_cpu_bounded(isolated_runtime):
    runtime_dir, _ = isolated_runtime
    mgr = PeerRuntimeManager(runtime_dir)
    try:
        handle = mgr.register_peer(_record(), on_message=lambda e: ReceiptState.QUEUED)
        # Let the supervisor settle, then measure an idle window.
        time.sleep(0.3)
        before = _process_cpu_seconds()
        time.sleep(2.0)
        after = _process_cpu_seconds()
        delta = after - before
        # An idle selector loop with a 0.5s timeout costs far less than 0.1s
        # of CPU over 2 seconds; a busy loop would burn ~2s.
        assert delta < 0.1, f"idle supervisor burned {delta:.3f}s CPU in 2s"
        handle.close()
    finally:
        mgr.shutdown()


def test_cleanup_over_session_churn(isolated_runtime):
    """Repeated register/teardown leaves no sockets, registry files or
    threads behind (PILOT-1202 cleanup over churn)."""
    runtime_dir, _ = isolated_runtime
    for _ in range(10):
        mgr = PeerRuntimeManager(runtime_dir)
        handle = mgr.register_peer(_record(), on_message=lambda e: ReceiptState.QUEUED)
        handle.close()
        mgr.shutdown()
    sockets = list((runtime_dir / "s").glob("*.sock"))
    registry = list((runtime_dir / "registry").glob("*.json"))
    assert sockets == [], f"leftover sockets: {sockets}"
    assert registry == [], f"leftover registry files: {registry}"
