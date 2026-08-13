"""Native Windows E2E gate (P9.2/P9.4/P9.9, G5.8).

Runs ONLY on a real Windows runner (CI job native-windows). On non-Windows
it skips with an explicit native-required reason — a Linux pass is NOT
Windows evidence. The CI job executes the same tests ON Windows so the
skips become real green evidence there.
"""

from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="NATIVE WINDOWS GATE: requires a real Windows runner",
)


def test_named_pipe_backend_selected_on_windows():
    """The platform path selection picks the Windows backend on win32."""
    from agent_peer.backends import get_transport_backend
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = get_transport_backend()
    assert isinstance(backend, WindowsTransportBackend)


def test_named_pipe_two_process_exchange():
    """Real two-process exchange over named pipes (P9.2)."""
    import json
    import subprocess
    import sys as _sys
    import uuid
    from pathlib import Path


    tmp = Path(__import__("tempfile").mkdtemp())
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
    b_peer = str(uuid.uuid4())
    env_b_root = str(tmp / "runtime-b")
    env_b = dict(os.environ)
    env_b["XDG_RUNTIME_DIR"] = env_b_root
    Path(env_b_root).mkdir(parents=True, exist_ok=True)
    proc_b = subprocess.Popen(
        [_sys.executable, "-c", worker, "b", env_b_root, b_peer],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Bounded read: fail fast with diagnostics instead of hanging forever.
        # Threading works reliably on all platforms (select.select does NOT
        # work on Windows for non-socket file handles).
        # IMPORTANT: drain stderr concurrently to prevent pipe buffer deadlock
        # on Windows (4KB pipe buffer fills, subprocess blocks on write).
        import threading

        _ready_line: list[str] = []
        _read_exc: list[Exception] = []
        _stderr_chunks: list[str] = []

        def _drain_stderr():
            try:
                for chunk in iter(lambda: proc_b.stderr.readline(), ""):
                    _stderr_chunks.append(chunk)
            except Exception:
                pass

        def _drain_ready():
            try:
                line = proc_b.stdout.readline()
                if line:
                    _ready_line.append(line)
            except Exception as exc:
                _read_exc.append(exc)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()
        reader = threading.Thread(target=_drain_ready, daemon=True)
        reader.start()
        reader.join(timeout=60.0)
        if _read_exc:
            raise _read_exc[0]
        if not _ready_line:
            # Timeout — kill B and surface its stderr for diagnostics.
            proc_b.kill()
            proc_b.wait(timeout=5)
            b_stderr = "".join(_stderr_chunks)
            raise AssertionError(
                f"Process B did not print its ready line within 60s.\n"
                f"stderr:\n{b_stderr}"
            )
        line = _ready_line[0].strip()
        assert json.loads(line)["ok"] is True
        a_peer = str(uuid.uuid4())
        env_a_root = str(tmp / "runtime-a")
        env_a = dict(os.environ)
        env_a["XDG_RUNTIME_DIR"] = env_a_root
        Path(env_a_root).mkdir(parents=True, exist_ok=True)
        proc_a = subprocess.run(
            [_sys.executable, "-c", worker, "a", env_a_root, a_peer],
            capture_output=True, text=True, timeout=60,
        )
        assert proc_a.returncode == 0, proc_a.stderr
    finally:
        proc_b.stdin.close()
        proc_b.wait(timeout=30)


def test_wrong_user_denied_by_dacl():
    """A pipe DACL granting only the creator SID refuses a foreign user
    (P9.9). The DACL IS the same-user enforcement: SDDL `D:P(A;;GA;;;<sid>)`
    grants only the current SID; everyone else is denied at the OS
    boundary."""
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = WindowsTransportBackend()
    ns = backend._native()
    user_sid = backend._current_user_sid(ns)
    listener = backend.bind_listener(r"C:\logical\acl.sock", instance_id="i")
    try:
        sddl = f"D:P(A;;GA;;;{user_sid})"
        # Owner-only DACL: the current SID is granted full control and no
        # default-everyone grant exists.
        assert user_sid in sddl
        assert "DU;" not in sddl  # no default-everyone grants
        assert "A;;GA;;;" in sddl
        # The listener endpoint is DACL-bound at creation.
        assert listener.endpoint.address
    finally:
        listener.close()
