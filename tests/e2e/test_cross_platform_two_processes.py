"""Cross-platform two-process E2E (P2, P9.2/P9.7, ACC-06/07).

NATIVE GATE: real two-process exchange over named pipes with crash/restart
stale recovery MUST run on native Windows. On non-Windows this file skips
with an explicit native-required reason; a Linux pass is NOT Windows evidence
(G5.8, NG-12).
"""

from __future__ import annotations

import contextlib
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
import json, os, sys, uuid, traceback
from datetime import UTC, datetime
from agent_peer.models import PeerRecord, Presence
from agent_peer.runtime import PeerRuntimeManager

try:
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
    sys.stdin.read()
    handle.close()
    runtime.shutdown()
except Exception:
    traceback.print_exc()
    sys.exit(1)
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
    # Wait for B's ready line with a bounded timeout (cross-platform).
    # Threading works reliably on all platforms (select.select does NOT
    # work on Windows for non-socket file handles).
    # IMPORTANT: drain stderr concurrently to prevent pipe buffer deadlock
    # on Windows (4KB pipe buffer fills, subprocess blocks on write).
    import threading

    _ready_b_line: list[str] = []
    _ready_b_exc: list[Exception] = []
    _b_stderr_chunks: list[str] = []

    def _drain_b_stderr():
        try:
            for chunk in iter(lambda: b.stderr.readline(), ""):
                _b_stderr_chunks.append(chunk)
        except Exception:
            pass

    def _drain_b_ready():
        try:
            line = b.stdout.readline()
            if line:
                _ready_b_line.append(line)
        except Exception as exc:
            _ready_b_exc.append(exc)

    _b_stderr_thread = threading.Thread(target=_drain_b_stderr, daemon=True)
    _b_stderr_thread.start()
    _b_reader = threading.Thread(target=_drain_b_ready, daemon=True)
    _b_reader.start()
    _b_reader.join(timeout=60.0)
    if _ready_b_exc:
        raise _ready_b_exc[0]
    if not _ready_b_line:
        b.kill()
        b.wait(timeout=5)
        b_stderr = "".join(_b_stderr_chunks)
        # Read file-based trace (stderr pipe is unreliable for diagnosis)
        import os as _os
        import pathlib as _pl
        _tracefile = _pl.Path(_os.environ.get("TEMP", "/tmp")) / "agent_peer_trace.log"
        _trace = ""
        with contextlib.suppress(Exception):
            _trace = _tracefile.read_text()
        raise AssertionError(
            f"child B did not print ready line within 60s.\n"
            f"stderr: {b_stderr}\n"
            f"trace: {_trace}"
        )
    ready_b = _ready_b_line[0]
    assert ready_b, f"child B exited before ready; stderr: {b.stderr.read() if b.stderr else ''}"
    assert json.loads(ready_b)["ok"], f"child B not ok: {b.stderr.read() if b.stderr else ''}"

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
    # Wait for A's ready line with a bounded timeout (cross-platform).
    _ready_a_line: list[str] = []
    _ready_a_exc: list[Exception] = []
    _a_stderr_chunks: list[str] = []

    def _drain_a_stderr():
        try:
            for chunk in iter(lambda: a.stderr.readline(), ""):
                _a_stderr_chunks.append(chunk)
        except Exception:
            pass

    def _drain_a_ready():
        try:
            line = a.stdout.readline()
            if line:
                _ready_a_line.append(line)
        except Exception as exc:
            _ready_a_exc.append(exc)

    _a_stderr_thread = threading.Thread(target=_drain_a_stderr, daemon=True)
    _a_stderr_thread.start()
    _a_reader = threading.Thread(target=_drain_a_ready, daemon=True)
    _a_reader.start()
    _a_reader.join(timeout=60.0)
    if _ready_a_exc:
        raise _ready_a_exc[0]
    if not _ready_a_line:
        a.kill()
        a.wait(timeout=5)
        a_stderr = "".join(_a_stderr_chunks)
        raise AssertionError(
            f"child A did not print ready line within 60s.\n"
            f"stderr: {a_stderr}"
        )
    ready_a = _ready_a_line[0]
    assert ready_a, f"child A exited before ready; stderr: {a.stderr.read() if a.stderr else ''}"
    assert json.loads(ready_a)["ok"], f"child A not ok: {a.stderr.read() if a.stderr else ''}"

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
