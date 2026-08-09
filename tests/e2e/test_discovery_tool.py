"""Cross-process discovery through the real plugin tool path (F-01, REM-101, ACC-01).

Proves the actual defect fix: ``peer_list_agents`` in process A must list a
peer registered by independent process B through the shared owner-local
runtime root. The historical implementation filtered registry records through
the local ``_peer_handles`` connection map, so a sibling process's record was
never listed. This test uses two real subprocesses, each driving the full
``PeerSessionManager`` + plugin tool surface (no direct registry pokes).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def _wait_for(predicate, timeout: float = 30.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class ToolWorker:
    """Subprocess driving PeerSessionManager + peer_list_agents/peer_send_message."""

    def __init__(self, runtime_dir: Path, state_dir: Path, session_id: str) -> None:
        self.proc = subprocess.Popen(
            [PYTHON, "-c", _TOOL_WORKER_SRC],
            env={
                **os.environ,
                "AGENT_PEER_RUNTIME_DIR": str(runtime_dir),
                "AGENT_PEER_STATE_DIR": str(state_dir),
                "PEER_SESSION_ID": session_id,
                "PYTHONPATH": str(REPO_ROOT),
            },
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        self.peer_id = self._wait_ready()

    def _wait_ready(self, timeout: float = 30.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("READY "):
                return line.split()[1]
            if self.proc.poll() is not None:
                raise RuntimeError(f"tool worker exited early: {self.proc.stderr.read()}")
        raise TimeoutError("tool worker did not become ready")

    def list_agents(self) -> dict:
        self.proc.stdin.write("LIST\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline().strip()
        return json.loads(line)

    def stop(self) -> None:
        try:
            self.proc.stdin.write("EXIT\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            self.proc.wait(timeout=5)


_TOOL_WORKER_SRC = r"""
import os, sys, json
from hermes_peer.plugin import register, get_manager

class Ctx:
    def __init__(self):
        self.injected = []
    def register_hook(self, n, cb):
        pass
    def register_tool(self, *a, **kw):
        pass
    def register_command(self, *a, **kw):
        pass
    def register_cli_command(self, *a, **kw):
        pass
    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        self.injected.append((content, target_session))
        return True

ctx = Ctx()
register(ctx)
mgr = get_manager()
mgr.on_session_start(os.environ["PEER_SESSION_ID"], platform="cli")
print("READY " + mgr.peer_id_for_session(os.environ["PEER_SESSION_ID"]), flush=True)
for line in sys.stdin:
    line = line.strip()
    if line == "EXIT":
        break
    if line == "LIST":
        from hermes_peer.tools import peer_list_agents
        print(peer_list_agents({}), flush=True)
mgr.shutdown()
"""


@pytest.fixture
def roots(tmp_path):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    runtime.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    return runtime, state


class TestToolCrossProcessDiscovery:
    def test_process_a_lists_process_b_via_tool(self, roots):
        runtime, state = roots
        a = ToolWorker(runtime, state / "a", "sess-a")
        b = ToolWorker(runtime, state / "b", "sess-b")
        try:
            # A must see B (and itself) through the actual tool.
            assert _wait_for(lambda: len(a.list_agents().get("peers", [])) >= 2)
            result = a.list_agents()
            peers = result["peers"]
            ids = {p["peer_id"] for p in peers}
            assert b.peer_id in ids
            names = {p["name"] for p in peers}
            assert any("sess" in n or n for n in names)
        finally:
            a.stop()
            b.stop()

    def test_b_listed_with_full_metadata(self, roots):
        runtime, state = roots
        a = ToolWorker(runtime, state / "a", "sess-a")
        b = ToolWorker(runtime, state / "b", "sess-b")
        try:
            assert _wait_for(lambda: len(a.list_agents().get("peers", [])) >= 2)
            result = a.list_agents()
            b_row = next(p for p in result["peers"] if p["peer_id"] == b.peer_id)
            for key in ("peer_id", "name", "profile", "surface", "status", "cwd"):
                assert key in b_row, f"missing {key} in {b_row}"
        finally:
            a.stop()
            b.stop()
