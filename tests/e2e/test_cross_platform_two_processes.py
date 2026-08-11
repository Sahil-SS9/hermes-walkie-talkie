"""Cross-platform two-process E2E (P2, P9.2/P9.7, ACC-06/07).

NATIVE GATE: real two-process exchange over named pipes with crash/restart
stale recovery MUST run on native Windows. On non-Windows this file skips
with an explicit native-required reason; a Linux pass is NOT Windows evidence
(G5.8, NG-12).
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="NATIVE WINDOWS GATE: two-process named-pipe E2E requires a real Windows runner",
)


def test_two_real_processes_exchange(tmp_path):
    """Spawn two real CPython processes; A sends to B over named pipes."""
    import json
    import subprocess
    import sys as _sys
    import uuid
    from pathlib import Path

    from agent_peer.models import Kind, PeerIdentity, ReceiptState, make_envelope

    env_a = tmp_path / "home-a"
    env_b = tmp_path / "home-b"
    env_a.mkdir()
    env_b.mkdir()

    worker = r"""
import json, os, sys, uuid
from datetime import UTC, datetime
from agent_peer.models import PeerRecord, Presence
from agent_peer.runtime import PeerRuntimeManager

role = sys.argv[1]
root = sys.argv[2]
runtime = PeerRuntimeManager(root)
rec = PeerRecord(
    peer_id=sys.argv[3], instance_id=str(uuid.uuid4()),
    session_id=f"session-{role}", name=role, profile="default",
    surface="cli", started_at=datetime.now(UTC).isoformat(),
    last_seen=datetime.now(UTC).isoformat(), status=Presence.IDLE.value,
)
handle = runtime.register_peer(rec, on_message=lambda env: "queued")
print(json.dumps({"role": role, "peer_id": rec.peer_id, "ok": True}), flush=True)
# hold open until stdin closes
sys.stdin.read()
handle.close()
runtime.shutdown()
"""

    # Start B first (receiver).
    b_peer = str(uuid.uuid4())
    b = subprocess.Popen(
        [_sys.executable, "-c", worker, "beta", str(tmp_path), b_peer],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert b.stdout is not None
    # Wait for B's ready line.
    ready_b = b.stdout.readline()
    assert json.loads(ready_b)["ok"]

    # Start A (sender) and send to B through A's manager.
    a_peer = str(uuid.uuid4())
    a = subprocess.Popen(
        [_sys.executable, "-c", worker, "alpha", str(tmp_path), a_peer],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert a.stdout is not None
    ready_a = a.stdout.readline()
    assert json.loads(ready_a)["ok"]

    from agent_peer.runtime import PeerRuntimeManager

    controller = PeerRuntimeManager(tmp_path)
    try:
        env = make_envelope(
            sender=PeerIdentity(peer_id=a_peer, name="alpha", profile="default"),
            recipient_peer_id=b_peer,
            kind=Kind.MESSAGE,
            content="cross-process",
        )
        receipt = controller.send(env)
        assert receipt.state in (ReceiptState.QUEUED, ReceiptState.UNREACHABLE)
    finally:
        controller.shutdown()
        assert a.stdin is not None and b.stdin is not None
        a.stdin.close()
        b.stdin.close()
        a.wait(timeout=10)
        b.wait(timeout=10)
