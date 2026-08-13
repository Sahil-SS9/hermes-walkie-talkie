"""Clean install/uninstall in a disposable Hermes home (E2E-909) and the
real-binary disposable smoke test (E2E-910)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
HERMES_BIN = Path(os.environ.get("HERMES_BIN", "/home/kensei/.local/bin/hermes"))


def _hermes_env(home: Path) -> dict:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    # The clone-style install must be the only repository source. Coverage and
    # orchestration harnesses may inject their own checkout into PYTHONPATH,
    # which would make a deleted clone reappear as an entry-point plugin.
    env.pop("PYTHONPATH", None)
    return env


class TestCleanInstall:
    def test_install_enable_restart_list_uninstall(self, tmp_path):
        """E2E-909: clone-style install, enable, restart, uninstall, cleanup."""
        if not HERMES_BIN.exists():
            pytest.skip("hermes binary not available")
        home = tmp_path / "home"
        home.mkdir()
        (home / "config.yaml").write_text("plugins:\n  enabled: []\n", encoding="utf-8")

        # Install from the clone-style layout (what a GitHub install yields).
        plugin_dir = home / "plugins" / "hermes-walkie-talkie"
        plugin_dir.parent.mkdir(parents=True)
        shutil.copytree(REPO_ROOT, plugin_dir, ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "__pycache__"))

        # Enable in config and list.
        (home / "config.yaml").write_text("plugins:\n  enabled: [hermes-peer]\n", encoding="utf-8")
        proc = subprocess.run(
            [str(HERMES_BIN), "plugins", "list"],
            env=_hermes_env(home), capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "hermes-peer" in proc.stdout and "enabled" in proc.stdout

        # Restart-equivalent: a second process sees the same enabled state.
        proc2 = subprocess.run(
            [str(HERMES_BIN), "plugins", "list"],
            env=_hermes_env(home), capture_output=True, text=True, timeout=120,
        )
        assert "hermes-peer" in proc2.stdout and "enabled" in proc2.stdout

        # Uninstall: disable the plugin in this temporary home and delete its
        # clone. A developer machine may also expose hermes-peer as an
        # entry-point plugin, so verify this home has it disabled.
        (home / "config.yaml").write_text("plugins:\n  enabled: []\n", encoding="utf-8")
        shutil.rmtree(plugin_dir)
        list_cmd = [str(HERMES_BIN), "plugins", "list", "--plain", "--no-bundled"]
        proc3 = subprocess.run(
            list_cmd,
            env=_hermes_env(home), capture_output=True, text=True, timeout=120,
        )
        assert proc3.returncode == 0, proc3.stderr
        assert not plugin_dir.exists()
        peer_rows = [line.split() for line in proc3.stdout.splitlines() if line.rstrip().endswith("hermes-peer")]
        # A clean install has no row. A developer environment may still expose
        # the package as an entry point, but this temporary home must not enable it.
        assert not peer_rows or peer_rows[0][:2] == ["not", "enabled"], proc3.stdout


class TestRealBinarySmoke:
    def test_two_disposable_homes_exchange_a_message(self, tmp_path):
        """E2E-910: two isolated local Hermes sessions under temporary homes
        exchange a harmless message through the real binary + installed
        plugin, with no model call and no live-profile mutation."""
        if not HERMES_BIN.exists():
            pytest.skip("hermes binary not available")

        home_a = tmp_path / "home-a"
        home_b = tmp_path / "home-b"
        for home in (home_a, home_b):
            home.mkdir()
            (home / "config.yaml").write_text("plugins:\n  enabled: [hermes-peer]\n", encoding="utf-8")
            plugin_dir = home / "plugins" / "hermes-walkie-talkie"
            plugin_dir.parent.mkdir(parents=True)
            shutil.copytree(REPO_ROOT, plugin_dir, ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "__pycache__"))

        # 1. Real binary loads the plugin in both homes (plugins list).
        for home, tag in ((home_a, "A"), (home_b, "B")):
            proc = subprocess.run(
                [str(HERMES_BIN), "plugins", "list"],
                env=_hermes_env(home), capture_output=True, text=True, timeout=120,
            )
            assert proc.returncode == 0, proc.stderr
            assert "hermes-peer" in proc.stdout, f"plugin not loaded in home {tag}"

        # 2. Cross-process exchange through the INSTALLED plugin package in
        #    each home: real registry + real sockets between two processes;
        #    inbound delivery lands in the session's inject file (the host
        #    seam is exercised via inject_message). No model call happens.
        script = r"""
import os, sys
sys.path.insert(0, os.environ["PLUGIN_DIR"])
from hermes_peer.plugin import register, get_manager

class Ctx:
    def register_hook(self, n, cb):
        pass
    def register_tool(self, *a, **kw):
        pass
    def register_command(self, *a, **kw):
        pass
    def register_cli_command(self, *a, **kw):
        pass
    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        with open(os.environ["INJECT_FILE"], "a", encoding="utf-8") as f:
            f.write(content + "\n")
        return True

ctx = Ctx()
register(ctx)
mgr = get_manager()
mgr.on_session_start(os.environ["SESSION_ID"], platform="cli")
# The discovery service lists ALL live peers (including cross-process ones),
# so [0] is not guaranteed to be this process's own peer. Use the exact
# session's peer id for the READY line (F-01/REM-203).
_my_peer = mgr.peer_id_for_session(os.environ["SESSION_ID"])
print("READY " + _my_peer, flush=True)
for line in sys.stdin:
    line = line.strip()
    if line == "EXIT":
        break
    if line.startswith("SEND "):
        parts = line.split(" ", 2)
        receipt = mgr.send_message(parts[1], parts[2])
        print("SENT " + receipt["state"] + " " + receipt["message_id"], flush=True)
mgr.shutdown()
"""
        script_path = tmp_path / "driver.py"
        script_path.write_text(script, encoding="utf-8")
        inject_a = tmp_path / "inject_a.log"
        inject_b = tmp_path / "inject_b.log"
        inject_a.touch()
        inject_b.touch()

        runtime = tmp_path / "runtime"
        runtime.mkdir(mode=0o700)

        def _env(home: Path, session_id: str, inject: Path) -> dict:
            env = _hermes_env(home)
            env["PLUGIN_DIR"] = str(home / "plugins" / "hermes-walkie-talkie")
            env["SESSION_ID"] = session_id
            env["INJECT_FILE"] = str(inject)
            env["XDG_RUNTIME_DIR"] = str(runtime)
            env["XDG_STATE_HOME"] = str(tmp_path / "state")
            return env

        procs: list[subprocess.Popen] = []
        try:
            p_a = subprocess.Popen(
                [sys.executable, str(script_path)],
                env=_env(home_a, "real-session-a", inject_a),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            procs.append(p_a)
            ready_a = p_a.stdout.readline().strip()
            assert ready_a.startswith("READY "), f"A: {ready_a!r} stderr={p_a.stderr.read()[-500:]!r}"

            p_b = subprocess.Popen(
                [sys.executable, str(script_path)],
                env=_env(home_b, "real-session-b", inject_b),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            procs.append(p_b)
            ready_b = p_b.stdout.readline().strip()
            assert ready_b.startswith("READY "), f"B: {ready_b!r} stderr={p_b.stderr.read()[-500:]!r}"
            peer_b = ready_b.split()[1]

            # Session A sends to session B.
            p_a.stdin.write(f"SEND {peer_b} hello from real session A\n")
            p_a.stdin.flush()
            sent = p_a.stdout.readline().strip()
            assert sent.startswith("SENT queued"), sent

            # B receives the message through its inject seam.
            deadline = time.monotonic() + 30
            received = False
            while time.monotonic() < deadline:
                text = inject_b.read_text(encoding="utf-8")
                if "hello from real session A" in text:
                    received = True
                    break
                time.sleep(0.2)
            if not received:
                err_a = p_a.stderr.read() if p_a.stderr else ""
                err_b = p_b.stderr.read() if p_b.stderr else ""
                raise AssertionError(
                    f"B never received the message; inject log: {inject_b.read_text()!r}; "
                    f"A stderr: {err_a[-500:]!r}; B stderr: {err_b[-500:]!r}"
                )
            assert "<peer_message>" in inject_b.read_text(encoding="utf-8")
        finally:
            for p in procs:
                try:
                    p.stdin.write("EXIT\n")
                    p.stdin.flush()
                    p.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    p.kill()
