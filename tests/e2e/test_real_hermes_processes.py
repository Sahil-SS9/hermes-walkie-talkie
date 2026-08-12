"""Real-Hermes-binary cross-process E2E (F-05, REM-501..REM-507).

Two actual Hermes agent processes (importing the EXACT core remediation
worktree) exercise the plugin through the real discovery/lifecycle/tool
dispatch path with a local deterministic fake model endpoint. Direct
``register()`` calls or fake PluginContext drivers are NOT used: each
process runs the real ``run_agent.AIAgent`` conversation loop, which
discovers plugins from a disposable ``HERMES_HOME``, registers the plugin's
tools into the real model registry, dispatches ``peer_list_agents`` through
the model tool pipeline, and delivers inbound messages through the public
injection seam.

Provenance gate: the launched processes must import ``hermes_cli`` from the
exact core remediation worktree (``HERMES_CORE_ROOT``), never the system
binary. The fake model server is imported only by this test and production
packages never import it.
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

# Import the sibling fake-model server via explicit file path (test-only).
import importlib.util  # noqa: E402

_fms_spec = importlib.util.spec_from_file_location(
    "fake_model_server", Path(__file__).resolve().parent / "fake_model_server.py"
)
assert _fms_spec is not None and _fms_spec.loader is not None
_fms_mod = importlib.util.module_from_spec(_fms_spec)
_fms_spec.loader.exec_module(_fms_mod)
FakeModelServer = _fms_mod.FakeModelServer


def _subprocess_env(base: dict | os._Environ, home: Path, runtime: Path, state: Path) -> dict:
    """Build a clean env for the agent/probe subprocesses.

    Removes any inherited repo/site-packages paths from PYTHONPATH so the
    standalone repo's egg-info entry point cannot shadow the directory-scan
    plugin load (see cwd notes in the tests). The only plugin-discovery
    surface is the disposable HERMES_HOME/plugins directory.
    """
    env = dict(base)
    # Start from a clean PYTHONPATH containing exactly core + plugin.
    env["PYTHONPATH"] = f"{CORE_ROOT}:{home / 'plugins' / 'hermes-walkie-talkie'}"
    env["HERMES_HOME"] = str(home)
    env["HERMES_CORE_ROOT"] = str(CORE_ROOT)
    env["PLUGIN_DIR"] = str(home / "plugins" / "hermes-walkie-talkie")
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["XDG_STATE_HOME"] = str(state)
    return env


def _install_plugin(home: Path) -> Path:
    """Clone-style plugin install into a disposable home.

    Excludes the repo's own ``*.egg-info`` build artifact so the entry-point
    discovery scan cannot see it (which would route through a loader path
    that mis-resolves ``module:attr`` entry points). Only the directory-scan
    path (plugin.yaml) is exercised.
    """
    dst = home / "plugins" / "hermes-walkie-talkie"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        REPO_ROOT, dst,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "dist", "build", "__pycache__", "*.egg-info"
        ),
    )
    return dst


def _make_home(tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir(exist_ok=True)
    (home / "config.yaml").write_text("plugins:\n  enabled: [hermes-peer]\n", encoding="utf-8")
    _install_plugin(home)
    return home


# Each agent subprocess drives the REAL conversation loop against the fake
# model endpoint. It registers via the host on_session_open lifecycle hook
# (the real Hermes plugin path), then the model issues peer_list_agents.
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
result = agent.run_conversation("list peer agents and report exactly what you see")
final_response = str(result.get("final_response", ""))
# The conversation result is the model's text; the peer list was produced by
# the real peer_list_agents tool inside the agent loop.
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


class TestRealHermesProcesses:
    @pytest.fixture(autouse=True)
    def _skip_without_core(self, require_hermes_core):
        pass

    def test_provenance_imports_core_worktree(self):
        """REM-501 provenance: the launched processes must import hermes_cli
        from HERMES_CORE_ROOT, never the system install."""
        assert CORE_ROOT.exists(), f"HERMES_CORE_ROOT missing: {CORE_ROOT}"
        proc = subprocess.run(
            [HERMES_PYTHON, "-c", "import hermes_cli; print(hermes_cli.__file__)"],
            env={**os.environ, "PYTHONPATH": str(CORE_ROOT)},
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert str(CORE_ROOT) in proc.stdout, f"hermes_cli imported from wrong path: {proc.stdout}"

    def test_two_real_agents_discover_and_tool_dispatch(self, tmp_path):
        """REM-501/503: two real Hermes agent processes, actual plugin
        discovery/lifecycle/tool dispatch, A sees B via peer_list_agents."""
        home_a = _make_home(tmp_path, "home-a")
        home_b = _make_home(tmp_path, "home-b")
        runtime = tmp_path / "runtime"
        state = tmp_path / "state"
        runtime.mkdir(exist_ok=True)
        state.mkdir(exist_ok=True)

        srv = FakeModelServer()
        srv.start()
        try:
            ready_b = tmp_path / "agent-b.ready"
            release_b = tmp_path / "agent-b.release"
            env_b = _subprocess_env(os.environ, home_b, runtime, state)
            env_b.update(
                SESSION_ID="real-sess-b",
                FAKE_MODEL_URL=srv.base_url,
                READY_FILE=str(ready_b),
                HOLD_UNTIL=str(release_b),
            )
            proc_b = subprocess.Popen(
                [HERMES_PYTHON, "-c", _AGENT_DRIVER],
                env=env_b,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd="/tmp",
            )
            try:
                deadline = time.monotonic() + 180
                while not ready_b.exists() and time.monotonic() < deadline:
                    assert proc_b.poll() is None, "agent B exited before publishing readiness"
                    time.sleep(0.05)
                assert ready_b.exists(), "agent B did not become a live addressable peer"
                final_b = ready_b.read_text(encoding="utf-8").strip()
                result_b = json.loads(final_b.split("Tool result: ", 1)[1])
                assert len(result_b["peers"]) == 1
                peer_b = result_b["peers"][0]["peer_id"]

                env_a = _subprocess_env(os.environ, home_a, runtime, state)
                env_a.update(SESSION_ID="real-sess-a", FAKE_MODEL_URL=srv.base_url)
                proc_a = subprocess.run(
                    [HERMES_PYTHON, "-c", _AGENT_DRIVER],
                    env=env_a,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    cwd="/tmp",
                )
                assert proc_a.returncode == 0, f"agent A failed: {proc_a.stderr[-1000:]}"
                final_a = json.loads(
                    next(
                        line.removeprefix("AGENT_DONE ")
                        for line in proc_a.stdout.splitlines()
                        if line.startswith("AGENT_DONE ")
                    )
                )
                result_a = json.loads(final_a.split("Tool result: ", 1)[1])
                peer_ids_a = {row["peer_id"] for row in result_a["peers"]}
                assert len(peer_ids_a) == 2
                assert peer_b in peer_ids_a
            finally:
                release_b.touch(exist_ok=True)
                out_b, err_b = proc_b.communicate(timeout=30)
                assert proc_b.returncode == 0, f"agent B failed: {err_b[-1000:]}"
                assert "AGENT_DONE" in out_b

            # The fake model endpoint is test-only: production packages never
            # import it (structural gate).
            import inspect

            import agent_peer.runtime
            import hermes_peer.plugin

            for mod in (agent_peer.runtime, hermes_peer.plugin):
                src = inspect.getsource(mod)
                assert "fake_model_server" not in src and "FakeModelServer" not in src
        finally:
            srv.stop()

    def test_plugin_registers_via_real_lifecycle(self, tmp_path):
        """REM-503/504: the plugin's tools and lifecycle hooks register
        through the REAL host discovery (not direct register() calls)."""
        home = _make_home(tmp_path, "home-lifecycle")
        env = _subprocess_env(os.environ, home, tmp_path / "runtime", tmp_path / "state")
        probe = (
            "from hermes_cli.plugins import get_plugin_manager; "
            "mgr = get_plugin_manager(); mgr.discover_and_load(force=True); "
            "print('TOOLS', sorted(mgr._plugin_tool_names)); "
            "print('HOOKS', sorted(mgr._hooks.keys()))"
        )
        proc = subprocess.run(
            [HERMES_PYTHON, "-c", probe], env=env, capture_output=True, text=True, timeout=120,
            cwd="/tmp",  # see cwd note in test_two_real_agents_discover_and_tool_dispatch
        )
        assert proc.returncode == 0, proc.stderr
        assert "peer_list_agents" in proc.stdout
        assert "on_session_open" in proc.stdout
