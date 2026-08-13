"""SEC-R1: Sender identity spoofing regression tests.

A peer cannot send a message with a forged sender identity.
PeerRuntimeManager.send() must authenticate the sender against its
registered peers and override the envelope sender with the bound record.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_peer.models import (
    PeerIdentity,
    PeerRecord,
    ReceiptState,
    make_envelope,
)
from agent_peer.runtime import PeerRuntimeManager


def _record(name: str = "peer") -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        last_seen=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def isolated_runtime():
    runtime_dir = Path(tempfile.mkdtemp(prefix="hwt-sec-r1-"))
    state_dir = Path(tempfile.mkdtemp(prefix="hwt-sec-r1-state-"))
    yield runtime_dir, state_dir


class TestSenderSpoofingPrevented:
    def test_forged_sender_rejected(self, isolated_runtime):
        """An envelope whose sender.peer_id is not a registered peer is
        rejected with INVALID — no delivery occurs.
        """
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        try:
            victim = _record("victim")
            mgr.register_peer(victim, lambda e: ReceiptState.QUEUED)

            forged_id = str(uuid.uuid4())
            env = make_envelope(
                sender=PeerIdentity(peer_id=forged_id, name="KENSEI", profile="default"),
                recipient_peer_id=victim.peer_id,
                content="forged authority",
            )
            receipt = mgr.send(env)
            assert receipt.state is ReceiptState.INVALID
            assert "not registered" in receipt.detail
        finally:
            mgr.shutdown()

    def test_registered_sender_accepted_with_authenticated_identity(self, isolated_runtime):
        """A registered peer sending under its own peer_id is accepted, and
        the recipient sees the authenticated name and profile from the bound
        record — not whatever the envelope claimed.
        """
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        seen = []
        try:
            victim = _record("victim")
            sender = PeerRecord(
                peer_id=str(uuid.uuid4()),
                instance_id=str(uuid.uuid4()),
                name="real-name",
                profile="real-profile",
                surface="cli",
                pid=os.getpid(),
                cwd="/tmp",
                last_seen=datetime.now(UTC).isoformat(),
            )
            mgr.register_peer(victim, lambda e: seen.append(e) or ReceiptState.QUEUED)
            mgr.register_peer(sender, lambda e: ReceiptState.QUEUED)

            # Envelope claims a DIFFERENT name and profile.
            env = make_envelope(
                sender=PeerIdentity(
                    peer_id=sender.peer_id,
                    name="forged-name",
                    profile="forged-profile",
                ),
                recipient_peer_id=victim.peer_id,
                content="auth test",
            )
            receipt = mgr.send(env)
            assert receipt.state is ReceiptState.QUEUED
            assert len(seen) == 1
            # The recipient sees the AUTHENTICATED identity.
            assert seen[0].sender.peer_id == sender.peer_id
            assert seen[0].sender.name == "real-name"
            assert seen[0].sender.profile == "real-profile"
        finally:
            mgr.shutdown()

    def test_sender_cannot_impersonate_another_registered_peer(self, isolated_runtime):
        """Peer A cannot send a message claiming to be from Peer B (both
        registered). The sender is authenticated from the runtime, not the
        envelope. Since the envelope's sender.peer_id matches A, the
        identity is stamped as A — not B.
        """
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        seen = []
        try:
            peer_a = _record("alice")
            peer_b = _record("bob")
            mgr.register_peer(peer_a, lambda e: seen.append(e) or ReceiptState.QUEUED)
            mgr.register_peer(peer_b, lambda e: ReceiptState.QUEUED)

            # Peer B tries to impersonate Peer A.
            env = make_envelope(
                sender=PeerIdentity(
                    peer_id=peer_b.peer_id,
                    name="alice-impersonated",
                    profile="fake",
                ),
                recipient_peer_id=peer_a.peer_id,
                content="spoof attempt",
            )
            receipt = mgr.send(env)
            assert receipt.state is ReceiptState.QUEUED
            # Peer A sees the real Bob identity, not "alice-impersonated".
            assert seen[0].sender.peer_id == peer_b.peer_id
            assert seen[0].sender.name == "bob"
            assert seen[0].sender.profile == "test"
        finally:
            mgr.shutdown()
