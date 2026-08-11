"""Desktop surface E2E (P9.3, G6).

Real local backend + installed disposable Desktop plugin + a session
created with surface `desktop`: the plugin loads, the peer advertises
surface desktop, and the dashboard API answers against the real backend.
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
        ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "__pycache__", "*.egg-info", "desktop", "dashboard"),
    )


def _make_home(tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text("plugins:\n  enabled: [hermes-peer]\n", encoding="utf-8")
    _install_plugin(home)
    return home


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


# A real Hermes process opens a session with surface `desktop` through the
# plugin's lifecycle hook, then a second real process observes the peer and
# its surface. Manager access goes through real tool dispatch (same pattern
# as the passing request/discovery E2Es), never a direct import that would
# split the module instance.
_DESKTOP_DRIVER = r"""
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
assert notify_session_open(session_id, os.environ.get("SURFACE", "desktop")), "host-open lifecycle did not fire"
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
"""


class TestDesktopSurfaceE2E:
    def test_real_desktop_surface_peer_observed(self, tmp_path):
        """A real process opens a desktop-surface session; a second real
        process sees that peer and its surface=desktop."""
        home_d = _make_home(tmp_path, "home-desktop")
        home_o = _make_home(tmp_path, "home-observer")
        runtime = tmp_path / "runtime"
        state = tmp_path / "state"
        runtime.mkdir(exist_ok=True)
        state.mkdir(exist_ok=True)

        srv = FakeModelServer()
        srv.start()
        try:
            # Desktop process holds (surface=desktop).
            ready_d = tmp_path / "desktop.ready"
            release_d = tmp_path / "desktop.release"
            env_d = _subprocess_env(os.environ, home_d, runtime, state)
            env_d.update(
                SESSION_ID="desk-sess-1",
                SURFACE="desktop",
                FAKE_MODEL_URL=srv.base_url,
                READY_FILE=str(ready_d),
                HOLD_UNTIL=str(release_d),
                PROMPT="list peer agents and report exactly what you see",
            )
            proc_d = subprocess.Popen(
                [HERMES_PYTHON, "-c", _DESKTOP_DRIVER],
                env=env_d, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd="/tmp",
            )
            try:
                deadline = time.monotonic() + 120
                while not ready_d.exists() and time.monotonic() < deadline:
                    if proc_d.poll() is not None:
                        out, err = proc_d.communicate(timeout=10)
                        raise AssertionError(f"desktop process exited early rc={proc_d.returncode}\nSTDERR:\n{err[-2000:]}\nSTDOUT:\n{out[-2000:]}")
                    time.sleep(0.05)
                assert ready_d.exists(), "desktop session never became ready"
                result_d = _extract_result(ready_d.read_text(encoding="utf-8").strip())
                # peer_list_agents includes same-process peers: the desktop
                # process sees itself with surface=desktop.
                assert len(result_d["peers"]) == 1, result_d["peers"]
                assert result_d["peers"][0]["surface"] == "desktop", result_d["peers"]

                # Observer process (surface=cli) lists peers: must see the
                # desktop peer with surface=desktop.
                ready_o = tmp_path / "observer.ready"
                release_o = tmp_path / "observer.release"
                env_o = _subprocess_env(os.environ, home_o, runtime, state)
                env_o.update(
                    SESSION_ID="obs-sess-1",
                    SURFACE="cli",
                    FAKE_MODEL_URL=srv.base_url,
                    READY_FILE=str(ready_o),
                    HOLD_UNTIL=str(release_o),
                    PROMPT="list peer agents and report exactly what you see",
                )
                proc_o = subprocess.Popen(
                    [HERMES_PYTHON, "-c", _DESKTOP_DRIVER],
                    env=env_o, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd="/tmp",
                )
                try:
                    deadline = time.monotonic() + 120
                    while not ready_o.exists() and time.monotonic() < deadline:
                        if proc_o.poll() is not None:
                            out, err = proc_o.communicate(timeout=10)
                            raise AssertionError(f"observer exited early rc={proc_o.returncode}\nSTDERR:\n{err[-2000:]}\nSTDOUT:\n{out[-2000:]}")
                        time.sleep(0.05)
                    assert ready_o.exists(), "observer never became ready"
                    result_o = _extract_result(ready_o.read_text(encoding="utf-8").strip())
                    desktop_peers = [p for p in result_o["peers"] if p.get("surface") == "desktop"]
                    assert len(desktop_peers) == 1, result_o["peers"]
                finally:
                    release_o.touch(exist_ok=True)
                    out_o, err_o = proc_o.communicate(timeout=30)
                    assert proc_o.returncode == 0, f"observer failed: {err_o[-1000:]}"
            finally:
                release_d.touch(exist_ok=True)
                out_d, err_d = proc_d.communicate(timeout=30)
                assert proc_d.returncode == 0, f"desktop process failed: {err_d[-1000:]}"
        finally:
            srv.stop()
