"""Busy-target queue-only delivery (P9.5).

A message to a busy (mid-turn) target must be queued or held — never
injected into the active loop. The delivery adapter uses the host's
mode=queue seam; when the host declines, the message stays HELD in the
store and is released on the next explicit drain. No active tool is ever
interrupted (the host owns the queue; this plugin has no interrupt seam).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_peer.models import Envelope, Kind, PeerIdentity, ReceiptState, make_envelope
from hermes_peer.delivery import DeliveryAdapter


class _QueueOnlyHost:
    """A host that always queues (never delivers into an active loop).

    Mirrors the real Hermes inject_message(mode=queue) contract: returns
    True (accepted into the queue) without touching any running tool.
    """

    def __init__(self) -> None:
        self.injected: list[tuple[str, str, str]] = []
        self.interrupt_attempts = 0

    def inject_message(self, text, *, role, mode, target_session):
        assert mode == "queue", f"delivery must be queue-only, got mode={mode!r}"
        self.injected.append((text, role, target_session))
        # A real host would interrupt an active tool only for mode=now; we
        # assert this never happens.
        if mode == "now":
            self.interrupt_attempts += 1
        return True


class _SessionManagerStub:
    def __init__(self, store) -> None:
        self._store = store
        self._record = None

    def resolve_peer(self, peer_id: str):
        if self._record is None:
            from agent_peer.models import PeerRecord, Presence

            self._record = PeerRecord(
                peer_id="33333333-3333-4333-8333-333333333333",
                instance_id="44444444-4444-4444-8444-444444444444",
                session_id="busy-session",
                name="busy",
                profile="",
                surface="cli",
                started_at="2026-01-01T00:00:00+00:00",
                last_seen="2026-01-01T00:00:00+00:00",
                status=Presence.HELD.value,
                host_target="cli:busy-session",
            )
        return self._record


def _stub_envelope(peer_id: str = "33333333-3333-4333-8333-333333333333") -> Envelope:
    return make_envelope(
        message_id="22222222-2222-4222-8222-222222222222",
        kind=Kind.MESSAGE,
        content="hello while busy",
        sender=PeerIdentity(
            peer_id="11111111-1111-4111-8111-111111111111",
            name="alice",
            profile="",
        ),
        recipient_peer_id=peer_id,
    )


class TestBusyTargetQueueOnly:
    def test_queue_only_never_interrupts(self):
        """The delivery adapter uses mode=queue; the host never sees an
        interrupt-capable delivery request."""
        host = _QueueOnlyHost()
        store_path = Path(tempfile.mkdtemp()) / "m.sqlite3"
        from agent_peer.store import MessageStore

        store = MessageStore(store_path)
        adapter = DeliveryAdapter(
            ctx=host,
            session_manager=_SessionManagerStub(store),
        )
        env = _stub_envelope()
        accepted = adapter.deliver(env)
        assert accepted is True
        assert host.interrupt_attempts == 0
        assert len(host.injected) == 1
        text, role, target = host.injected[0]
        assert role == "user"
        # Delivery targets the host's opaque routing token (host_target),
        # never the raw peer_id.
        assert target == "cli:busy-session"
        assert "<peer_message>" in text
        # Stored as QUEUED — waiting for the host's queue, not the loop.
        row = store.get("22222222-2222-4222-8222-222222222222")
        assert row is not None
        assert row["state"] == ReceiptState.QUEUED.value

    def test_held_when_host_declines(self):
        """If the host refuses (e.g. session gone), the message is HELD and
        remains durable — never silently dropped or force-injected."""
        host = _QueueOnlyHost()

        def refuse(text, *, role="user", mode="queue", target_session=None) -> bool:
            return False

        host.inject_message = refuse  # type: ignore[method-assign]  # runtime override for this case
        from agent_peer.store import MessageStore

        store = MessageStore(Path(tempfile.mkdtemp()) / "m.sqlite3")
        adapter = DeliveryAdapter(
            ctx=host,
            session_manager=_SessionManagerStub(store),
        )
        env = _stub_envelope()
        accepted = adapter.deliver(env)
        assert accepted is False
        assert host.interrupt_attempts == 0
        row = store.get("22222222-2222-4222-8222-222222222222")
        assert row is not None
        assert row["state"] == ReceiptState.HELD.value

    def test_duplicate_delivery_is_deduplicated(self):
        """The same message_id is delivered at most once (P9.8 adjacent)."""
        host = _QueueOnlyHost()
        from agent_peer.store import MessageStore

        store = MessageStore(Path(tempfile.mkdtemp()) / "m.sqlite3")
        adapter = DeliveryAdapter(
            ctx=host,
            session_manager=_SessionManagerStub(store),
        )
        env = _stub_envelope()
        assert adapter.deliver(env) is True
        assert adapter.deliver(env) is False  # deduplicated
        assert len(host.injected) == 1
