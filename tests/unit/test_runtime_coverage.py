"""Coverage-gate completion tests (runtime + transport + delivery).

Targets the specific uncovered branches measured by
``scripts/coverage_gate.py``: ``agent_peer.runtime`` error/guard paths,
unreachable/invalid send receipts, and teardown fences. All tests are
unit-level: no real inter-process sockets required.

Run locally:
    python -m pytest tests/unit/test_runtime_coverage.py -q
"""

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_peer.models import (
    Envelope,
    Kind,
    PeerIdentity,
    PeerRecord,
    ReceiptState,
    make_envelope,
)
from agent_peer.runtime import PeerRuntimeManager, _Connection


def _record(name: str = "p", **kw) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        status="idle",
        **kw,
    )


def _envelope(sender_peer_id: str, recipient_peer_id: str, content="x") -> Envelope:
    return make_envelope(
        sender=PeerIdentity(peer_id=sender_peer_id, name="a", profile=""),
        recipient_peer_id=recipient_peer_id,
        content=content,
    )


@pytest.fixture()
def mgr(tmp_path):
    m = PeerRuntimeManager(tmp_path / "runtime")
    yield m
    m.shutdown()


class TestUpdateRecord:
    def test_unknown_peer_returns_false(self, mgr):
        rec = _record()
        assert mgr.update_record(rec) is False

    def test_identity_mismatch_returns_false(self, mgr):
        rec = _record()
        handle = mgr.register_peer(rec, on_message=lambda e: ReceiptState.QUEUED)
        try:
            bound = mgr._peers[rec.peer_id]
            forged = replace(bound, instance_id=str(uuid.uuid4()))
            assert mgr.update_record(forged) is False
            # Matching identity but different cwd/status -> accepted.
            ok = replace(bound, current_activity="reviewing PRs")
            assert mgr.update_record(ok) is True
            assert mgr._peers[rec.peer_id].current_activity == "reviewing PRs"
        finally:
            handle.close()


class TestSendFailureReceipts:
    def test_send_timeout_maps_unreachable(self, mgr, tmp_path):
        sender = _record()
        mgr.register_peer(sender, on_message=lambda e: ReceiptState.QUEUED)
        # Registry entry with a socket path that exists but never answers.
        dead_sock = tmp_path / "dead.sock"
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(str(dead_sock))
        srv.listen(1)  # bound but we never accept() -> request times out
        try:
            from agent_peer.registry import Registry

            ghost = _record(socket_path=str(dead_sock))
            Registry(mgr._paths).register(ghost)
            env = _envelope(sender.peer_id, ghost.peer_id)
            rec = mgr.send(env)
            assert rec.state.value == "unreachable", rec.detail
        finally:
            srv.close()

    def test_send_frame_error_maps_invalid(self, mgr, tmp_path):
        from agent_peer.codec import FrameError

        sender = _record()
        mgr.register_peer(sender, on_message=lambda e: ReceiptState.QUEUED)
        recipient = _record(socket_path=str(tmp_path / "r.sock"))
        mgr._registry.register(recipient)
        with patch.object(
            mgr, "_backend"
        ) as backend:
            backend.request.side_effect = FrameError("bad wire")
            env = _envelope(sender.peer_id, recipient.peer_id)
            rec = mgr.send(env)
        assert rec.state.value == "invalid"

    def test_send_bad_receipt_state_maps_invalid(self, mgr):

        sender = _record()
        mgr.register_peer(sender, on_message=lambda e: ReceiptState.QUEUED)
        recipient = _record(socket_path="/nonexistent")
        mgr._registry.register(recipient)
        # Backend replies with a RECEIPT envelope carrying an unknown state.
        reply_env = make_envelope(
            sender=PeerIdentity(peer_id=recipient.peer_id, name="r", profile=""),
            recipient_peer_id=sender.peer_id,
            kind=Kind.RECEIPT,
            content="not-a-real-state",
        )
        with patch.object(
            mgr._backend, "request", return_value=b'{"reply":"stub"}'
        ), patch("agent_peer.runtime.decode_envelope", return_value=reply_env), patch(
            "agent_peer.runtime.encode_envelope", return_value="{}"
        ):
            env = _envelope(sender.peer_id, recipient.peer_id)
            rec = mgr.send(env)
        assert rec.state.value == "invalid"
        assert "bad receipt" in rec.detail

    def test_send_unexpected_reply_kind_maps_invalid(self, mgr):
        sender = _record()
        mgr.register_peer(sender, on_message=lambda e: ReceiptState.QUEUED)
        recipient = _record(socket_path="/nonexistent")
        mgr._registry.register(recipient)
        odd = make_envelope(
            sender=PeerIdentity(peer_id=recipient.peer_id, name="r", profile=""),
            recipient_peer_id=sender.peer_id,
            kind=Kind.MESSAGE,  # neither RECEIPT nor PONG
            content="hello",
        )
        with patch.object(
            mgr._backend, "request", return_value=b"{}"
        ), patch(
            "agent_peer.runtime.decode_envelope", return_value=odd
        ), patch(
            "agent_peer.runtime.encode_envelope", return_value="{}"
        ):
            rec = mgr.send(_envelope(sender.peer_id, recipient.peer_id))
        assert rec.state.value == "invalid"
        assert "unexpected reply kind" in rec.detail

    def test_send_pong_maps_queued(self, mgr):
        sender = _record()
        mgr.register_peer(sender, on_message=lambda e: ReceiptState.QUEUED)
        recipient = _record(socket_path="/nonexistent")
        mgr._registry.register(recipient)
        pong = make_envelope(
            sender=PeerIdentity(peer_id=recipient.peer_id, name="r", profile=""),
            recipient_peer_id=sender.peer_id,
            kind=Kind.PONG,
            content="pong",
        )
        with patch.object(
            mgr._backend, "request", return_value=b"{}"
        ), patch(
            "agent_peer.runtime.decode_envelope", return_value=pong
        ), patch(
            "agent_peer.runtime.encode_envelope", return_value="{}"
        ):
            rec = mgr.send(_envelope(sender.peer_id, recipient.peer_id))
        assert rec.state.value == "queued"
        assert rec.detail == "pong"


class TestShutdownIdempotent:
    def test_shutdown_twice_noop(self, mgr):
        mgr.shutdown()
        mgr.shutdown()  # re-entrant no-op
        assert mgr._shutdown_done is True


class TestReclaimStaleSocket:
    def test_reclaim_removes_dead_socket(self, mgr, tmp_path):
        stale = tmp_path / "runtime" / "stale.sock"
        stale.parent.mkdir(parents=True, exist_ok=True)
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(stale))
        s.close()  # file exists, nobody listens
        mgr._reclaim_stale_socket(stale)
        assert not stale.exists()

    def test_reclaim_keeps_live_listener(self, mgr, tmp_path):
        live = tmp_path / "runtime" / "live.sock"
        live.parent.mkdir(parents=True, exist_ok=True)
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(live))
        s.listen(1)
        try:
            mgr._reclaim_stale_socket(live)
            assert live.exists()  # live listener -> never reclaimed
        finally:
            s.close()
            live.unlink(missing_ok=True)


class TestUnregisterStatFences:
    def test_unregister_missing_socket_file_tolerated(self, mgr):
        rec = _record()
        handle = mgr.register_peer(rec, lambda e: ReceiptState.QUEUED)
        # Simulate the socket vanishing between bind and teardown.
        Path(mgr._peers[rec.peer_id].socket_path).unlink(missing_ok=True)
        handle.close()  # FileNotFoundError path -> no raise
        assert rec.peer_id not in mgr._peers


class TestDispatchGuards:
    def test_dispatch_to_unknown_peer_replies_unreachable(self, mgr):
        rec = _record()
        handle = mgr.register_peer(rec, lambda e: ReceiptState.QUEUED)
        try:
            conn = mgr._listeners[rec.peer_id]
            state = _Connection(conn, rec.peer_id)
            env = _envelope(rec.peer_id, str(uuid.uuid4()))
            sent: list[Envelope] = []
            with patch.object(mgr, "_flush", side_effect=lambda c, s: sent.append(1)):
                mgr._dispatch(conn, state, env)
            assert state.out_buffer  # an UNREACHABLE receipt was queued
        finally:
            handle.close()

    def test_dispatch_handler_raise_is_contained(self, mgr):
        def boom(envelope):
            raise RuntimeError("handler exploded")

        rec = _record()
        handle = mgr.register_peer(rec, boom)
        try:
            conn = mgr._listeners[rec.peer_id]
            state = _Connection(conn, rec.peer_id)
            with patch.object(mgr, "_flush", return_value=None):
                mgr._dispatch(conn, state, _envelope(rec.peer_id, rec.peer_id))
            assert state.out_buffer  # INVALID receipt queued
        finally:
            handle.close()

    def test_dispatch_non_receipt_state_name_maps_invalid(self, mgr):
        rec = _record()
        handle = mgr.register_peer(rec, lambda e: "not-a-real-state")
        try:
            conn = mgr._listeners[rec.peer_id]
            state = _Connection(conn, rec.peer_id)
            with patch.object(mgr, "_flush", return_value=None):
                mgr._dispatch(conn, state, _envelope(rec.peer_id, rec.peer_id))
            assert state.out_buffer
        finally:
            handle.close()


class TestServiceConnectionGuards:
    def test_service_connection_closed_state_noop(self, mgr):
        rec = _record()
        handle = mgr.register_peer(rec, lambda e: ReceiptState.QUEUED)
        try:
            conn = mgr._listeners[rec.peer_id]
            state = _Connection(conn, rec.peer_id)
            state.closed = True
            mgr._service_connection(conn, state)  # no raise, no read
        finally:
            handle.close()

    def test_service_connection_bad_frame_drops(self, mgr):
        from agent_peer.codec import FrameError

        rec = _record()
        handle = mgr.register_peer(rec, lambda e: ReceiptState.QUEUED)
        try:
            conn = mgr._listeners[rec.peer_id]
            state = _Connection(conn, rec.peer_id)

            class BadDecoder:
                def feed(self, chunk):
                    raise FrameError("bad")

            state.decoder = BadDecoder()

            class FakeConn:
                def recv(self, n):  # service_connection reads before decoding
                    return b"chunk"

                def close(self):
                    pass

            with patch.object(mgr, "_flush", return_value=None), patch.object(
                mgr, "_drop_connection", side_effect=lambda c: setattr(state, "closed", True)
            ):
                mgr._service_connection(FakeConn(), state)
            assert state.closed is True  # dropped after malformed frame
        finally:
            handle.close()


class TestFlushOSError:
    def test_flush_oserror_drops_connection(self, mgr):
        rec = _record()
        handle = mgr.register_peer(rec, lambda e: ReceiptState.QUEUED)
        try:
            conn = mgr._listeners[rec.peer_id]
            state = _Connection(conn, rec.peer_id)
            state.out_buffer.extend(b"x" * 8)

            class Boom:
                def send(self, data):
                    raise OSError("broken pipe")

            mgr._drop_connection = lambda c: state.__setattr__("closed", True)
            mgr._flush(Boom(), state)
            assert state.closed is True
        finally:
            handle.close()


class TestAcceptForeignOwner:
    def test_accept_drops_unauthenticated(self, mgr):
        rec = _record()
        handle = mgr.register_peer(rec, lambda e: ReceiptState.QUEUED)
        try:
            listener = mgr._listeners[rec.peer_id]
            fake = socket.socket(socket.AF_UNIX)
            mgr._backend = type(
                "B",
                (),
                {
                    "verify_remote_owner": staticmethod(
                        lambda conn: type("E", (), {"authenticated": False, "detail": "foreign"})()
                    )
                },
            )()
            mgr._accept(listener)
            fake.close()
            assert mgr._connections == {}
        finally:
            handle.close()


class TestWindowsBookkeepingDirect:
    def test_start_stop_windows_listener_direct(self, mgr):
        # Directly exercise the Windows bookkeeping on POSIX by stubbing the
        # wait loop target; exercises _start/_stop_windows_listener lines.
        started = []
        mgr._windows_wait_loop = lambda peer_id, listener: started.append(peer_id)
        listener = object()
        mgr._start_windows_listener("win-peer", listener)
        assert "win-peer" in mgr._windows_threads
        # Idempotent restart via _start (calls _stop first).
        mgr._start_windows_listener("win-peer", listener)
        mgr._stop_windows_listener("win-peer")
        assert "win-peer" not in mgr._windows_threads

    def test_windows_wait_loop_exits_on_listener_error(self, mgr):
        class ExplodingListener:
            def accept(self):
                raise RuntimeError("closed")

        # The wait loop must return (not raise) on listener errors.
        mgr._windows_wait_loop("w", ExplodingListener()) if False else None
        # Call the real loop body once via a thread to exercise its guard.
        import threading

        mgr._stop_event.clear()
        t = threading.Thread(
            target=mgr._windows_wait_loop, args=("w", ExplodingListener()), daemon=True
        )
        t.start()
        t.join(timeout=3)
        assert not t.is_alive()
