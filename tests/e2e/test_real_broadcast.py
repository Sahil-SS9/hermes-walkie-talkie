"""Real two-Hermes broadcast E2E (P9.1, G3).

Two actual Hermes agent processes drive the group/broadcast tools through
the real model tool pipeline (deferred search -> describe -> call) against
the fake model endpoint. Agent A creates a group, adds agent B by stable
agent_id, broadcasts; agent B's host receives the message through the real
local transport. Real native process evidence — not class imports.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = Path(os.environ.get("HERMES_CORE_ROOT", "/home/kensei/worktrees/hermes-walkie-talkie-core-remediation-r2"))
HERMES_PYTHON = os.environ.get("HERMES_PYTHON", "/home/kensei/repos/KenseiAgent/.venv/bin/python")

import importlib.util  # noqa: E402

_fms_spec = importlib.util.spec_from_file_location(
    "fake_model_server", Path(__file__).resolve().parent / "fake_model_server.py"
)
assert _fms_spec is not None and _fms_spec.loader is not None
_fms_mod = importlib.util.module_from_spec(_fms_spec)
_fms_spec.loader.exec_module(_fms_mod)
FakeModelServer = _fms_mod.FakeModelServer


def _subprocess_env(base, home: Path, runtime: Path, state: Path) -> dict:
    env = dict(base)
    env["PYTHONPATH"] = f"{CORE_ROOT}:{home / 'plugins' / 'hermes-walkie-talkie'}"
    env["HERMES_HOME"] = str(home)
    env["HERMES_CORE_ROOT"] = str(CORE_ROOT)
    env["PLUGIN_DIR"] = str(home / "plugins" / "hermes-walkie-talkie")
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["XDG_STATE_HOME"] = str(state)
    return env


def _install_plugin(home: Path) -> None:
    dst = home / "plugins" / "hermes-walkie-talkie"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        REPO_ROOT, dst,
        ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "__pycache__", "*.egg-info"),
    )


def _make_home(tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text("plugins:\n  enabled: [hermes-peer]\n", encoding="utf-8")
    _install_plugin(home)
    return home


_AGENT_DRIVER = r"""
import os, sys, json, time
sys.path.insert(0, os.environ["HERMES_CORE_ROOT"])
sys.path.insert(0, os.environ["PLUGIN_DIR"])
from run_agent import AIAgent
from hermes_cli.plugins import discover_plugins, notify_session_open

session_id = os.environ["SESSION_ID"]
base_url = os.environ["FAKE_MODEL_URL"]
discover_plugins()
agent = AIAgent(
    base_url=base_url,
    model="fake-model",
    api_key="fake",
    enabled_toolsets=["hermes-peer"],
    session_id=session_id,
)
assert notify_session_open(session_id, "e2e"), "host-open lifecycle did not fire"
result = agent.run_conversation(os.environ.get("PROMPT", "list peer agents and report exactly what you see"))
final_response = str(result.get("final_response", ""))
print("AGENT_DONE " + json.dumps(final_response), flush=True)
ready_file = os.environ.get("READY_FILE")
if ready_file:
    with open(ready_file, "w", encoding="utf-8") as handle:
        handle.write(final_response)
hold_until = os.environ.get("HOLD_UNTIL")
if hold_until:
    deadline = time.monotonic() + 120
    while not os.path.exists(hold_until) and time.monotonic() < deadline:
        time.sleep(0.05)
    if not os.path.exists(hold_until):
        raise TimeoutError("release marker was not created")
"""


def _extract_result(stdout: str) -> dict:
    text = stdout.strip()
    if "AGENT_DONE " in text:
        line = next(
            (ln for ln in text.splitlines() if ln.startswith("AGENT_DONE ")),
            "",
        )
        assert line, "agent did not print AGENT_DONE"
        text = json.loads(line.removeprefix("AGENT_DONE "))
    if not isinstance(text, str):
        return text
    assert "Tool result: " in text, f"no tool result embedded: {text[:200]}"
    return json.loads(text.split("Tool result: ", 1)[1])


class TestRealBroadcastE2E:
    def test_real_two_hermes_broadcast(self, tmp_path):
        """A creates a group, adds B, broadcasts; B's host receives it."""
        home_a = _make_home(tmp_path, "home-a")
        home_b = _make_home(tmp_path, "home-b")
        runtime = tmp_path / "runtime"
        state = tmp_path / "state"
        runtime.mkdir(exist_ok=True)
        state.mkdir(exist_ok=True)

        srv = FakeModelServer()
        srv.start()
        try:
            # B holds first so the test can learn B's agent_id.
            ready_b = tmp_path / "agent-b.ready"
            release_b = tmp_path / "agent-b.release"
            env_b = _subprocess_env(os.environ, home_b, runtime, state)
            env_b.update(
                SESSION_ID="bc-sess-b",
                FAKE_MODEL_URL=srv.base_url,
                READY_FILE=str(ready_b),
                HOLD_UNTIL=str(release_b),
                PROMPT="list peer agents and report exactly what you see",
            )
            proc_b = subprocess.Popen(
                [HERMES_PYTHON, "-c", _AGENT_DRIVER],
                env=env_b, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd="/tmp",
            )
            try:
                deadline = time.monotonic() + 180
                while not ready_b.exists() and time.monotonic() < deadline:
                    assert proc_b.poll() is None, "agent B exited before publishing readiness"
                    time.sleep(0.05)
                assert ready_b.exists(), "agent B did not become live"
                result_b = _extract_result(ready_b.read_text(encoding="utf-8").strip())
                assert len(result_b["peers"]) == 1
                agent_b = result_b["peers"][0]["agent_id"]

                # Agent A: create group -> add B -> broadcast, via real tools.
                # The group_id is created at runtime by the first tool call,
                # so a callable script threads it into the later calls — the
                # full flow runs through real deferred dispatch.
                broadcast_script = [
                    ("tool_search", {"query": "peer_group_manage", "limit": 5}),
                    ("tool_describe", {"name": "peer_group_manage"}),
                    (
                        "tool_call",
                        {
                            "name": "peer_group_manage",
                            "arguments": {"action": "create", "name": "e2e-team"},
                        },
                    ),
                ]
                group_id_box: dict = {}

                def broadcast_flow(tool_messages: list[dict]) -> tuple | None:
                    results = [
                        str(m.get("content") or "") for m in tool_messages
                    ]
                    step = len(results)
                    if step == 0:
                        return broadcast_script[0]
                    if step == 1:
                        return broadcast_script[1]
                    if step == 2:
                        return broadcast_script[2]
                    if step == 3:
                        # create result: {"group_id": ..., "name": ...}
                        create_result = json.loads(results[-1])
                        group_id_box["group_id"] = create_result["group_id"]
                        return ("tool_call", {
                            "name": "peer_group_manage",
                            "arguments": {
                                "action": "add_member",
                                "group_id": group_id_box["group_id"],
                                "member_agent_id": agent_b,
                            },
                        })
                    if step == 4:
                        return ("tool_search", {"query": "peer_broadcast", "limit": 5})
                    if step == 5:
                        return ("tool_describe", {"name": "peer_broadcast"})
                    if step == 6:
                        return ("tool_call", {
                            "name": "peer_broadcast",
                            "arguments": {
                                "group_id": group_id_box["group_id"],
                                "message": "hello from A",
                            },
                        })
                    return None  # finish — emit final response

                srv_a = FakeModelServer(script_fn=broadcast_flow)
                srv_a.start()
                try:
                    env_a = _subprocess_env(os.environ, home_a, runtime, state)
                    env_a.update(
                        SESSION_ID="bc-sess-a",
                        FAKE_MODEL_URL=srv_a.base_url,
                        PROMPT="broadcast a message to the e2e team",
                    )
                    proc_a = subprocess.run(
                        [HERMES_PYTHON, "-c", _AGENT_DRIVER],
                        env=env_a, capture_output=True, text=True, timeout=180, cwd="/tmp",
                    )
                    assert proc_a.returncode == 0, f"agent A failed: {proc_a.stderr[-1000:]}"
                    broadcast = _extract_result(proc_a.stdout)
                    summary = broadcast.get("summary", {})
                    per_member = broadcast.get("per_member", [])
                    # B is mid-conversation (holding), so the delivery adapter
                    # correctly holds the child: state is 'held', not 'queued'
                    # — queue-only delivery, never an active-loop interrupt
                    # (P9.5). Either delivered state proves the real
                    # transport carried the message.
                    assert summary.get("queued") + summary.get("held", 0) >= 1, broadcast
                    assert summary.get("unreachable") == 0, broadcast
                    assert len(per_member) == 1, per_member
                    assert per_member[0]["state"] in ("queued", "held"), per_member
                finally:
                    srv_a.stop()

                # Manager-level assertion of real delivery: B's store must
                # contain the broadcast content (real transport, same state
                # dir).
                import sqlite3

                db = state / "agent-peer" / "messages.sqlite3"
                conn = sqlite3.connect(db)
                try:
                    rows = conn.execute(
                        "SELECT content, state FROM messages WHERE content LIKE '%hello from A%'"
                    ).fetchall()
                finally:
                    conn.close()
                assert rows, "broadcast content never reached B's store"
                assert rows[0][1] in ("queued", "held"), rows[0]
            finally:
                release_b.touch(exist_ok=True)
                out_b, err_b = proc_b.communicate(timeout=30)
                assert proc_b.returncode == 0, f"agent B failed: {err_b[-1000:]}"
                assert "AGENT_DONE" in out_b
        finally:
            srv.stop()
