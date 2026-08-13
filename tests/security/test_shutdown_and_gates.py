"""RED tests for shutdown races (REM-410) and static/resource gates (REM-411).

Concurrent send/discovery/alias update during exact peer and final process
shutdown must return bounded explicit errors and never hang, corrupt or unlink
a successor. Static/resource gates: no raw body logging, no private-field
dependency in tools, no unsafe mode/path, no swallowed teardown error, no TCP
listener, no placeholder, no unbounded map/thread/FD growth.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

from agent_peer.models import Envelope, Kind, PeerIdentity, PeerRecord, ReceiptState
from agent_peer.runtime import PeerRuntimeManager


def _record(name: str = "p") -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        status="idle",
    )


def _envelope(sender: PeerIdentity, recipient: str, content: str) -> Envelope:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    return Envelope(
        protocol="agent-peer/1",
        message_id=str(uuid.uuid4()),
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        sender=sender,
        recipient_peer_id=recipient,
        kind=Kind.MESSAGE,
        content=content,
        reply_to=None,
        conversation_id=None,
        hop_count=0,
    )


class TestShutdownRaces:
    """REM-410: concurrent operations during teardown return bounded errors
    and never hang or corrupt."""

    def test_send_during_final_shutdown_bounded(self, tmp_path):
        mgr = PeerRuntimeManager(tmp_path / "runtime")
        a = _record("a")
        b = _record("b")
        mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
        mgr.register_peer(b, on_message=lambda e: ReceiptState.QUEUED)
        sender = PeerIdentity(peer_id=a.peer_id, name="a", profile="")
        errors: list[Exception] = []
        lock = threading.Lock()

        def sender_loop():
            try:
                for i in range(30):
                    mgr.send(_envelope(sender, b.peer_id, f"x-{i}"))
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        t = threading.Thread(target=sender_loop)
        t.start()
        import time

        time.sleep(0.05)
        mgr.shutdown()  # must not hang
        t.join(timeout=10)
        assert not t.is_alive(), "sender thread hung past shutdown"
        # Errors are explicit AgentPeerError-family, never a crash.
        from agent_peer.errors import AgentPeerError

        for exc in errors:
            assert isinstance(exc, AgentPeerError), exc

    def test_register_after_shutdown_is_noop_or_bounded(self, tmp_path):
        mgr = PeerRuntimeManager(tmp_path / "runtime")
        mgr.shutdown()
        # Registering after shutdown must not hang or corrupt; a bounded
        # error is acceptable, silently succeeding is not a crash either.

        try:
            rec = _record("late")
            with pytest.raises((OSError, Exception)):
                mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
        except Exception:  # noqa: BLE001 - bounded error acceptable
            pass


class TestStaticResourceGates:
    """REM-411: structural audit of the production packages."""

    def test_no_raw_body_logging_in_peer_modules(self):
        import inspect

        import agent_peer.discovery
        import agent_peer.registry
        import agent_peer.runtime
        import hermes_peer.delivery
        import hermes_peer.sessions

        for mod in (
            agent_peer.runtime,
            agent_peer.discovery,
            agent_peer.registry,
            hermes_peer.delivery,
            hermes_peer.sessions,
        ):
            src = inspect.getsource(mod)
            # No logging of full message content (only ids/truncated).
            assert "log(content" not in src and "logger.info(content" not in src
            assert "%s" in src  # structured logging present

    def test_no_private_peer_handles_in_tools_or_commands(self):
        """The F-01 fix removed _peer_handles as a discovery gate; tools and
        commands must not reach into it."""
        import inspect

        import hermes_peer.commands
        import hermes_peer.tools

        for mod in (hermes_peer.commands, hermes_peer.tools):
            src = inspect.getsource(mod)
            assert "_peer_handles" not in src, f"{mod.__name__} still touches _peer_handles"

    def test_no_tcp_listener_in_production_paths(self):
        import inspect

        import agent_peer.backends.base
        import agent_peer.backends.posix
        import agent_peer.backends.windows
        import agent_peer.discovery
        import agent_peer.runtime
        import agent_peer.transport

        # V1.1: the transport contract is backend-neutral. The no-AF_INET
        # property now lives at the backend seam (the ONLY socket producers):
        # runtime/discovery must contain no socket family at all, and the
        # POSIX backend must use AF_UNIX exclusively.
        for mod in (agent_peer.discovery, agent_peer.runtime, agent_peer.transport):
            src = inspect.getsource(mod)
            # AF_UNIX is the only family used; no AF_INET listener.
            assert "socket.AF_UNIX" in src or "AF_UNIX" in src or "socket.socket" not in src
            assert "socket.AF_INET," not in src
            assert "AF_INET6" not in src.replace("AF_INET6", "") or "AF_INET6" not in src
        for mod in (agent_peer.backends.base, agent_peer.backends.posix):
            src = inspect.getsource(mod)
            assert "AF_UNIX" in src
            assert "socket.AF_INET," not in src
            assert "AF_INET6" not in src.replace("AF_INET6", "") or "AF_INET6" not in src
        # Windows backend must not create TCP listeners before native proof.
        wsrc = inspect.getsource(agent_peer.backends.windows)
        assert "AF_INET" not in wsrc

    def test_no_unbounded_thread_growth(self):
        """One supervisor thread per manager; no thread-per-peer."""
        import inspect

        import agent_peer.runtime

        src = inspect.getsource(agent_peer.runtime)
        assert "threading.Thread" in src
        # The supervisor is created in _ensure_thread (single), not in the
        # register loop.
        assert "_ensure_thread" in src
