"""Windows runtime integration tests (P2.5, P2.6).

NATIVE GATE: these exercise named-pipe listeners through the real
PeerRuntimeManager and MUST run on native Windows. On non-Windows they skip
with an explicit native-required reason — never green evidence.
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="NATIVE WINDOWS GATE: runtime+named-pipe tests require a real Windows runner",
)


def _record(name: str, runtime_dir):
    from agent_peer.models import PeerRecord, Presence

    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        session_id=f"session-{name}",
        name=name,
        profile="default",
        surface="cli",
        started_at=datetime.now(UTC).isoformat(),
        last_seen=datetime.now(UTC).isoformat(),
        status=Presence.IDLE.value,
    )


def test_two_peers_message_exchange(tmp_path):
    """Real Windows backend: A -> supervisor -> B and receipt back."""
    from agent_peer.models import Kind, PeerIdentity, ReceiptState, make_envelope
    from agent_peer.runtime import PeerRuntimeManager

    runtime = PeerRuntimeManager(tmp_path)
    delivered: list[str] = []
    a = _record("alpha", tmp_path)
    b = _record("beta", tmp_path)
    ha = runtime.register_peer(a, on_message=lambda env: ReceiptState.QUEUED)
    hb = runtime.register_peer(
        b,
        on_message=lambda env: delivered.append(env.content) or ReceiptState.QUEUED,
    )
    try:
        env = make_envelope(
            sender=PeerIdentity(peer_id=a.peer_id, name="alpha", profile="default"),
            recipient_peer_id=b.peer_id,
            kind=Kind.MESSAGE,
            content="hello-beta",
        )
        receipt = runtime.send(env)
        assert receipt.state is ReceiptState.QUEUED
        assert delivered == ["hello-beta"]
    finally:
        ha.close()
        hb.close()
        runtime.shutdown()


def test_unreachable_peer_receipt(tmp_path):
    from agent_peer.models import Kind, PeerIdentity, ReceiptState, make_envelope
    from agent_peer.runtime import PeerRuntimeManager

    runtime = PeerRuntimeManager(tmp_path)
    a = _record("alpha", tmp_path)
    ha = runtime.register_peer(a, on_message=lambda env: ReceiptState.QUEUED)
    try:
        env = make_envelope(
            sender=PeerIdentity(peer_id=a.peer_id, name="alpha", profile="default"),
            recipient_peer_id=str(uuid.uuid4()),
            kind=Kind.MESSAGE,
            content="nobody-home",
        )
        receipt = runtime.send(env)
        assert receipt.state is ReceiptState.UNREACHABLE
    finally:
        ha.close()
        runtime.shutdown()


def test_teardown_never_unlinks_replacement(tmp_path):
    """Crash/stale: teardown of an old instance must not break a replacement."""
    from agent_peer.runtime import PeerRuntimeManager

    first = PeerRuntimeManager(tmp_path)
    a = _record("alpha", tmp_path)
    ha = first.register_peer(a, on_message=lambda env: "queued")
    # A second manager (replacement incarnation) binds the same peer.
    second = PeerRuntimeManager(tmp_path)
    a2 = _record("alpha", tmp_path)
    ha2 = second.register_peer(a2, on_message=lambda env: "queued")
    try:
        # Old teardown must not delete the replacement's socket.
        ha.close()
        assert ha2.socket_path.exists()
    finally:
        ha2.close()
        first.shutdown()
        second.shutdown()
