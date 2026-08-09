"""Peer worker subprocess for cross-process E2E tests (P9).

Usage:
    python peer_worker.py --runtime DIR --name NAME --out FILE [--policy accept|hold|refuse]

Registers a peer with the shared owner-local runtime root, prints
``READY <peer_id>`` to stdout, then serves messages until stdin closes or
SIGTERM. Each inbound message is written as ``MSG <message_id> <content>``
to the out file. Commands on stdin:

    SEND <peer_id> <text>            -> send a message, print ``SENT <receipt-state> <message_id>``
    REPLY <peer_id> <reply_to> <text> -> send a reply with reply_to, print ``SENT ...``
    EXIT                             -> unregister cleanly and exit

The worker models the harness-neutral core path exactly: registry +
supervisor + policy + store, no Hermes.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_peer.identity import generate_instance_id, generate_peer_id  # noqa: E402
from agent_peer.models import Envelope, Kind, PeerIdentity, PeerRecord, ReceiptState  # noqa: E402
from agent_peer.paths import RuntimePaths  # noqa: E402
from agent_peer.policy import PolicyEngine  # noqa: E402
from agent_peer.runtime import PeerRuntimeManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--policy", default="accept")
    args = parser.parse_args()

    paths = RuntimePaths(Path(args.runtime))
    runtime = PeerRuntimeManager(paths)
    policy = PolicyEngine(policy=args.policy)
    out = open(args.out, "a", encoding="utf-8")  # noqa: SIM115 - held open for the worker lifetime
    me = PeerRecord(
        peer_id=generate_peer_id(),
        instance_id=generate_instance_id(),
        name=args.name,
        profile="e2e",
        surface="cli",
        pid=os.getpid(),
        cwd=os.getcwd(),
        started_at=datetime.now(UTC).isoformat(),
        last_seen=datetime.now(UTC).isoformat(),
        status="idle",
    )

    def on_message(envelope: Envelope) -> ReceiptState:
        policy.register_pending(envelope.recipient_peer_id, 0)
        decision = policy.evaluate(envelope)
        out.write(f"MSG {envelope.message_id} {envelope.content}\n")
        out.flush()
        return decision.state

    handle = runtime.register_peer(me, on_message=on_message)
    print(f"READY {me.peer_id}", flush=True)

    def _stop(_sig, _frame):
        handle.close()
        runtime.shutdown()
        out.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 2)
            cmd = parts[0]
            if cmd == "SEND" and len(parts) == 3:
                target, text = parts[1], parts[2]
                env = _envelope(me, target, text)
                receipt = runtime.send(env)
                print(f"SENT {receipt.state.value} {receipt.message_id}", flush=True)
            elif cmd == "REPLY" and len(parts) == 3:
                target, rest = parts[1], parts[2]
                reply_to, text = rest.split(" ", 1)
                env = _envelope(me, target, text, reply_to=reply_to)
                receipt = runtime.send(env)
                print(f"SENT {receipt.state.value} {receipt.message_id}", flush=True)
            elif cmd == "EXIT":
                break
    finally:
        handle.close()
        runtime.shutdown()
        out.close()
    return 0


def _envelope(sender: PeerRecord, recipient: str, content: str, reply_to: str | None = None) -> Envelope:
    now = datetime.now(UTC)
    return Envelope(
        protocol="agent-peer/1",
        message_id=str(uuid.uuid4()),
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        sender=PeerIdentity(peer_id=sender.peer_id, name=sender.name, profile=sender.profile),
        recipient_peer_id=recipient,
        kind=Kind.MESSAGE,
        content=content,
        reply_to=reply_to,
        conversation_id=None,
        hop_count=0,
    )


if __name__ == "__main__":
    sys.exit(main())
