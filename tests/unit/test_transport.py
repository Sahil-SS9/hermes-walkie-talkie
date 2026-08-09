"""RED tests for the Unix-socket sender client and peer-credential checks (AP-502, AP-505)."""

from __future__ import annotations

import contextlib
import os
import socket
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_peer.codec import FrameDecoder, encode_envelope
from agent_peer.errors import AgentPeerError, TimeoutError_, UnreachableError
from agent_peer.models import Envelope, Kind, PeerIdentity
from agent_peer.transport import PeerClient, peer_credentials, verify_peer_credentials

NOW = datetime.now(UTC)


def _envelope(recipient: str, kind: Kind = Kind.PING, content: str = "ping") -> Envelope:
    return Envelope(
        protocol="agent-peer/1",
        message_id=str(uuid.uuid4()),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="tester", profile="default"),
        recipient_peer_id=recipient,
        kind=kind,
        content=content,
        reply_to=None,
        conversation_id=None,
        hop_count=0,
    )


class _EchoServer:
    """Minimal AF_UNIX server: replies pong to ping, receipt to message."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen(8)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.received: list[Envelope] = []

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        dec = FrameDecoder()
        conn.settimeout(5)
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                for env in dec.feed(chunk):
                    self.received.append(env)
                    from agent_peer.codec import encode_frame

                    if env.kind is Kind.PING:
                        reply = _envelope(env.sender.peer_id, Kind.PONG, "pong")
                    else:
                        reply = _envelope(env.sender.peer_id, Kind.RECEIPT, "queued")
                    conn.sendall(encode_frame(encode_envelope(reply)))
        except OSError:
            pass
        finally:
            conn.close()

    def close(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self.sock.close()
        with contextlib.suppress(OSError):
            self.path.unlink()


@pytest.fixture
def echo_server(tmp_path):
    server = _EchoServer(tmp_path / "echo.sock")
    server.start()
    yield server
    server.close()


class TestPeerCredentials:
    def test_peer_credentials_return_own_uid(self):
        creds = peer_credentials()
        assert creds["uid"] == os.geteuid()
        assert creds["pid"] == os.getpid()

    def test_verify_accepts_same_uid(self):
        assert verify_peer_credentials({"uid": os.geteuid()}) is True

    def test_verify_rejects_different_uid(self):
        assert verify_peer_credentials({"uid": os.geteuid() + 1}) is False

    def test_verify_rejects_missing_uid(self):
        assert verify_peer_credentials({}) is False


class TestPeerClient:
    def test_ping_round_trip(self, echo_server):
        client = PeerClient(str(echo_server.path))
        reply = client.request(_envelope(str(uuid.uuid4()), Kind.PING, "ping"))
        assert reply.kind is Kind.PONG
        assert reply.content == "pong"

    def test_message_receives_receipt(self, echo_server):
        client = PeerClient(str(echo_server.path))
        reply = client.request(_envelope(str(uuid.uuid4()), Kind.MESSAGE, "hi"))
        assert reply.kind is Kind.RECEIPT
        assert reply.content == "queued"

    def test_unreachable_socket_raises(self, tmp_path):
        client = PeerClient(str(tmp_path / "missing.sock"))
        with pytest.raises(UnreachableError):
            client.request(_envelope(str(uuid.uuid4()), Kind.PING, "x"))

    def test_receipt_timeout_raises(self, tmp_path):
        # A listener that accepts but never answers.
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        path = tmp_path / "silent.sock"
        sock.bind(str(path))
        sock.listen(1)

        def _accept() -> None:
            conn, _ = sock.accept()
            try:
                # Consume data but NEVER reply — the client must time out.
                while conn.recv(4096):
                    pass
            except OSError:
                pass

        threading.Thread(target=_accept, daemon=True).start()
        try:
            client = PeerClient(str(path), receipt_timeout=0.5)
            with pytest.raises(TimeoutError_):
                client.request(_envelope(str(uuid.uuid4()), Kind.PING, "x"))
        finally:
            with contextlib.suppress(OSError):
                sock.close()

    def test_errors_are_agent_peer_errors(self, tmp_path):
        client = PeerClient(str(tmp_path / "nope.sock"))
        with pytest.raises(AgentPeerError):
            client.request(_envelope(str(uuid.uuid4()), Kind.PING, "x"))
