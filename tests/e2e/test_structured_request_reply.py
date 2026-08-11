"""Real two-Hermes structured request/reply E2E (P5 gate, G4).

Two actual Hermes agent processes drive the request tools through the real
model tool pipeline (deferred search -> describe -> call) against the fake
model endpoint. Agent A creates a request addressed to agent B's agent_id;
agent B's host receives the inert <peer_request> boundary and completes the
workflow. Proves: request queued -> accepted -> progress -> completed, and
the request is conversational input that cannot invoke protected controls.
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


# Agent driver: real conversation loop; the model issues the request tools.
_REQUEST_DRIVER = r"""
import os, sys, json, time
sys.path.insert(0, os.environ["HERMES_CORE_ROOT"])
sys.path.insert(0, os.environ["PLUGIN_DIR"])
from run_agent import AIAgent
from hermes_cli.plugins import discover_plugins, notify_session_open

session_id = os.environ["SESSION_ID"]
base_url = os.environ["FAKE_MODEL_URL"]
discover_plugins()
agent = AIAgent(
    base_url=base_url, model="fake-model", api_key="fake",
    enabled_toolsets=["hermes-peer"], session_id=session_id,
)
assert notify_session_open(session_id, "e2e"), "host-open lifecycle did not fire"
result = agent.run_conversation(os.environ["PROMPT"])
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
    """Parse the last tool result from a driver's stdout or ready file.

    The AGENT_DONE line carries the JSON-encoded final response; the ready
    file carries the raw final response (no prefix). Both embed the last
    tool result after ``Tool result: ``.
    """
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


class TestStructuredRequestE2E:
    def test_real_two_hermes_request_workflow(self, tmp_path):
        """Agent A creates a request to agent B; B's host receives it as inert
        conversational input; the workflow completes through the tools."""
        home_a = _make_home(tmp_path, "home-a")
        home_b = _make_home(tmp_path, "home-b")
        runtime = tmp_path / "runtime"
        state = tmp_path / "state"
        runtime.mkdir(exist_ok=True)
        state.mkdir(exist_ok=True)

        # Start agent B held, with the discovery script: it lists peers so the
        # test can learn B's agent_id, then holds until released.
        srv = FakeModelServer()
        srv.start()
        try:
            ready_b = tmp_path / "agent-b.ready"
            release_b = tmp_path / "agent-b.release"
            env_b = _subprocess_env(os.environ, home_b, runtime, state)
            env_b.update(
                SESSION_ID="req-sess-b",
                FAKE_MODEL_URL=srv.base_url,
                READY_FILE=str(ready_b),
                HOLD_UNTIL=str(release_b),
                PROMPT="list peer agents and report exactly what you see",
            )
            proc_b = subprocess.Popen(
                [HERMES_PYTHON, "-c", _REQUEST_DRIVER],
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

                # Agent A creates a structured request addressed to B's agent_id.
                request_script = [
                    ("tool_search", {"query": "peer_request_create", "limit": 5}),
                    ("tool_describe", {"name": "peer_request_create"}),
                    (
                        "tool_call",
                        {
                            "name": "peer_request_create",
                            "arguments": {
                                "target_agent_id": agent_b,
                                "summary": "please summarise the inbox",
                            },
                        },
                    ),
                ]
                srv_a = FakeModelServer(script=request_script)
                srv_a.start()
                try:
                    env_a = _subprocess_env(os.environ, home_a, runtime, state)
                    env_a.update(
                        SESSION_ID="req-sess-a",
                        FAKE_MODEL_URL=srv_a.base_url,
                        PROMPT="create a structured request to agent B",
                    )
                    proc_a = subprocess.run(
                        [HERMES_PYTHON, "-c", _REQUEST_DRIVER],
                        env=env_a, capture_output=True, text=True, timeout=180, cwd="/tmp",
                    )
                    assert proc_a.returncode == 0, f"agent A failed: {proc_a.stderr[-1000:]}"
                    created = _extract_result(proc_a.stdout)
                    assert created["request_id"]
                    assert created["delivered"] is True
                    request_id = created["request_id"]

                    # Recipient B completes the workflow through its tools.
                    respond_script = [
                        ("tool_search", {"query": "peer_request_status", "limit": 5}),
                        ("tool_describe", {"name": "peer_request_status"}),
                        (
                            "tool_call",
                            {
                                "name": "peer_request_status",
                                "arguments": {"request_id": request_id},
                            },
                        ),
                        ("tool_search", {"query": "peer_request_respond", "limit": 5}),
                        ("tool_describe", {"name": "peer_request_respond"}),
                        (
                            "tool_call",
                            {
                                "name": "peer_request_respond",
                                "arguments": {"request_id": request_id, "action": "accept"},
                            },
                        ),
                        (
                            "tool_call",
                            {
                                "name": "peer_request_respond",
                                "arguments": {
                                    "request_id": request_id,
                                    "action": "progress",
                                    "detail": "working",
                                },
                            },
                        ),
                        (
                            "tool_call",
                            {
                                "name": "peer_request_respond",
                                "arguments": {
                                    "request_id": request_id,
                                    "action": "complete",
                                    "detail": "done",
                                },
                            },
                        ),
                    ]
                    srv_b = FakeModelServer(script=respond_script)
                    srv_b.start()
                    try:
                        env_b2 = _subprocess_env(os.environ, home_b, runtime, state)
                        env_b2.update(
                            SESSION_ID="req-sess-b2",
                            FAKE_MODEL_URL=srv_b.base_url,
                            PROMPT="respond to the pending structured request",
                        )
                        proc_b2 = subprocess.run(
                            [HERMES_PYTHON, "-c", _REQUEST_DRIVER],
                            env=env_b2, capture_output=True, text=True, timeout=180, cwd="/tmp",
                        )
                        assert proc_b2.returncode == 0, f"agent B respond failed: {proc_b2.stderr[-1000:]}"
                        # The final tool result is the completed transition.
                        final_resp = _extract_result(proc_b2.stdout)
                        assert final_resp.get("state") == "completed", f"unexpected final: {final_resp}"
                    finally:
                        srv_b.stop()
                finally:
                    srv_a.stop()
            finally:
                release_b.touch(exist_ok=True)
                out_b, err_b = proc_b.communicate(timeout=30)
                assert proc_b.returncode == 0, f"agent B failed: {err_b[-1000:]}"
        finally:
            srv.stop()
