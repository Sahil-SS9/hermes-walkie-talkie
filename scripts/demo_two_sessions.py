#!/usr/bin/env python3
"""Deterministic two-session demo (REL-1106).

Spawns two worker subprocesses that register as peers in a disposable
owner-local runtime root, sends a message from session A to session B, gets
the transport receipt, and shows B's reply with reply_to correlation.

No external API key, no network, no Hermes required — pure agent_peer over
real AF_UNIX sockets.

Usage:
    uv run python scripts/demo_two_sessions.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "tests" / "fixtures" / "peer_worker.py"


def _wait_ready(proc, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if line.startswith("READY "):
            return line.split()[1]
        if proc.poll() is not None:
            raise RuntimeError(f"worker exited early: {proc.stderr.read()}")
    raise TimeoutError("worker did not become ready")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-peer-demo-") as td:
        root = Path(td)
        runtime = root / "runtime"
        out_a = root / "out_a.log"
        out_b = root / "out_b.log"

        a = subprocess.Popen(
            [sys.executable, str(WORKER), "--runtime", str(runtime), "--name", "architect", "--out", str(out_a)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        b = subprocess.Popen(
            [sys.executable, str(WORKER), "--runtime", str(runtime), "--name", "backend", "--out", str(out_b)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            peer_a = _wait_ready(a)
            peer_b = _wait_ready(b)
            print(f"Session A (architect) ready: {peer_a[:8]}…")
            print(f"Session B (backend)   ready: {peer_b[:8]}…")

            # Discovery: both peers visible in the shared registry.
            from agent_peer.paths import RuntimePaths
            from agent_peer.registry import Registry

            registry = Registry(RuntimePaths(runtime))
            names = {p.name for p in registry.list_peers()}
            print(f"Discovery: {sorted(names)}")

            a.stdin.write(f"SEND {peer_b} The API schema changed: tenant_id replaces account_id.\\n")
            a.stdin.flush()
            sent = a.stdout.readline().strip()
            print(f"A → B receipt: {sent}")

            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                msgs = [
                    l for l in out_b.read_text(encoding="utf-8").splitlines()
                    if l.startswith("MSG ")
                ]
                if msgs:
                    break
                time.sleep(0.2)
            print(f"B received: {msgs[0]}")
            reply_to = msgs[0].split()[1]

            b.stdin.write(f"REPLY {peer_a} {reply_to} Migration finished successfully.\\n")
            b.stdin.flush()
            replied = b.stdout.readline().strip()
            print(f"B → A receipt: {replied}")

            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                a_msgs = [
                    l for l in out_a.read_text(encoding="utf-8").splitlines()
                    if l.startswith("MSG ")
                ]
                if a_msgs:
                    break
                time.sleep(0.2)
            print(f"A received reply: {a_msgs[0]}")
            print("Demo complete: discovery, send, receipt, reply and correlation all worked.")
        finally:
            for p in (a, b):
                try:
                    p.stdin.write("EXIT\n")
                    p.stdin.flush()
                    p.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
