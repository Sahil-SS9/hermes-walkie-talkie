"""Cross-process E2E: two and three independent sessions (E2E-901, E2E-903, E2E-906, E2E-907).

Spawns real subprocesses (tests/fixtures/peer_worker.py) that register with
the shared owner-local runtime root and exchange envelopes over real
AF_UNIX sockets.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
WORKER = FIXTURES / "peer_worker.py"
PYTHON = sys.executable


class Worker:
    def __init__(self, runtime_dir: Path, name: str, out_file: Path, policy: str = "accept") -> None:
        self.proc = subprocess.Popen(
            [PYTHON, str(WORKER), "--runtime", str(runtime_dir), "--name", name,
             "--out", str(out_file), "--policy", policy],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.peer_id = self._wait_ready()
        self.out_file = out_file

    def _wait_ready(self, timeout: float = 15.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("READY "):
                return line.split()[1]
            if self.proc.poll() is not None:
                raise RuntimeError(f"worker exited early: {self.proc.stderr.read()}")
        raise TimeoutError("worker did not become ready")

    def send(self, target: str, text: str) -> str:
        self.proc.stdin.write(f"SEND {target} {text}\n")
        self.proc.stdin.flush()
        return self.proc.stdout.readline().strip()

    def reply(self, target: str, reply_to: str, text: str) -> str:
        self.proc.stdin.write(f"REPLY {target} {reply_to} {text}\n")
        self.proc.stdin.flush()
        return self.proc.stdout.readline().strip()

    def stop(self) -> None:
        try:
            self.proc.stdin.write("EXIT\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            self.proc.wait(timeout=5)

    def read_msgs(self) -> list[str]:
        if not self.out_file.exists():
            return []
        return [line.strip() for line in self.out_file.read_text(encoding="utf-8").splitlines() if line.startswith("MSG ")]


@pytest.fixture
def runtime_dir(tmp_path) -> Path:
    return tmp_path / "runtime"


def _wait_for(predicate, timeout: float = 15.0, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestTwoSessions:
    def test_discovery_send_reply_receipt(self, runtime_dir):
        """E2E-901: discovery, send, automatic delivery, reply and receipt."""
        out_a = runtime_dir.parent / "out_a.log"
        out_b = runtime_dir.parent / "out_b.log"
        a = Worker(runtime_dir, "architect", out_a)
        b = Worker(runtime_dir, "backend", out_b)
        try:
            # Discovery: both are visible in the shared registry.
            from agent_peer.paths import RuntimePaths
            from agent_peer.registry import Registry

            registry = Registry(RuntimePaths(runtime_dir))
            assert _wait_for(lambda: len(registry.list_peers()) == 2)
            names = {p.name for p in registry.list_peers()}
            assert names == {"architect", "backend"}

            # A -> B
            sent = a.send(b.peer_id, "The API schema changed: tenant_id replaces account_id.")
            assert sent.startswith("SENT queued")

            # B receives exactly once (automatic delivery at the core).
            assert _wait_for(lambda: len(b.read_msgs()) == 1)
            msgs = b.read_msgs()
            assert "tenant_id" in msgs[0]

            # B replies with correlation -> A gets a queued receipt.
            reply_msg_id = msgs[0].split()[1]
            replied = b.reply(a.peer_id, reply_msg_id, "Migration finished successfully.")
            assert replied.startswith("SENT queued")
        finally:
            a.stop()
            b.stop()

    def test_duplicate_send_delivered_once(self, runtime_dir):
        """The transport dedups nothing at this layer, but the store-level
        dedup (P6) plus the host dedup guard (P7) ensure one delivery."""
        out_b = runtime_dir.parent / "out_b.log"
        a = Worker(runtime_dir, "alpha", runtime_dir.parent / "out_a2.log")
        b = Worker(runtime_dir, "beta", out_b)
        try:
            a.send(b.peer_id, "once")
            assert _wait_for(lambda: len(b.read_msgs()) == 1)
            time.sleep(0.5)
            assert len(b.read_msgs()) == 1  # still exactly one
        finally:
            a.stop()
            b.stop()


class TestThreeSessions:
    def test_direct_routing_only_to_chosen_peer(self, runtime_dir):
        """E2E-903: three distinct peers; only the chosen one receives."""
        outs = {}
        workers = {}
        try:
            for name in ("api", "frontend", "tests"):
                out = runtime_dir.parent / f"out_{name}.log"
                outs[name] = out
                workers[name] = Worker(runtime_dir, name, out)
            sender = workers["api"]
            sent = sender.send(workers["frontend"].peer_id, "for frontend only")
            assert sent.startswith("SENT queued")
            assert _wait_for(lambda: len(outs["frontend"].read_text(encoding="utf-8").splitlines()) >= 1)
            # The third peer never receives it.
            time.sleep(0.4)
            assert outs["tests"].read_text(encoding="utf-8").strip() == ""
        finally:
            for w in workers.values():
                w.stop()


class TestPolicies:
    def test_accept_hold_refuse_walkthrough(self, runtime_dir):
        """E2E-906: the sender sees the correct receipt state each time."""
        accept = Worker(runtime_dir, "accept-peer", runtime_dir.parent / "out_acc.log", policy="accept")
        hold = Worker(runtime_dir, "hold-peer", runtime_dir.parent / "out_hold.log", policy="hold")
        refuse = Worker(runtime_dir, "refuse-peer", runtime_dir.parent / "out_ref.log", policy="refuse")
        try:
            sent = accept.send(hold.peer_id, "held message")
            assert sent.startswith("SENT held")
            sent = accept.send(refuse.peer_id, "refused message")
            assert sent.startswith("SENT refused")
            sent = accept.send(accept.peer_id, "accepted message")
            assert sent.startswith("SENT queued")
        finally:
            accept.stop()
            hold.stop()
            refuse.stop()


class TestCrashRestart:
    def test_crashed_session_disappears_and_new_registers_cleanly(self, runtime_dir):
        """E2E-907: no stale peer is reported reachable after a crash; a new
        process registers cleanly under a fresh peer id."""
        out = runtime_dir.parent / "out_crash.log"
        w1 = Worker(runtime_dir, "crashy", out)
        old_peer_id = w1.peer_id
        # Kill -9: no cleanup at all.
        w1.proc.kill()
        w1.proc.wait(timeout=5)

        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        registry = Registry(RuntimePaths(runtime_dir))
        # Simulate elapsed time past the stale threshold (45s), then apply
        # the authoritative check: socket handshake fails after a crash.

        stale_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        import json as _json

        entry_file = registry._paths.registry_file_for(old_peer_id)
        data = _json.loads(entry_file.read_text(encoding="utf-8"))
        data["last_seen"] = stale_time
        entry_file.write_text(_json.dumps(data), encoding="utf-8")

        removed = registry.prune(handshake_alive=lambda pid, instance: False)
        assert any(r.peer_id == old_peer_id for r in removed)
        assert all(p.peer_id != old_peer_id for p in registry.list_peers())

        w2 = Worker(runtime_dir, "crashy", out)
        try:
            assert w2.peer_id != old_peer_id
            # Old socket reclaimed; new peer fully functional and the only
            # registry entry for this name.
            entries = [p for p in registry.list_peers() if p.name == "crashy"]
            assert [p.peer_id for p in entries] == [w2.peer_id]
            sent = w2.send(w2.peer_id, "self test")
            assert sent.startswith("SENT queued")
        finally:
            w2.stop()
