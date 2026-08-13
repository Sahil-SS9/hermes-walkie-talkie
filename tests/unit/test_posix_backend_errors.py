"""POSIX backend fail-closed error branches (P11.1 coverage).

Exercises the rejection paths that a malformed or foreign peer can hit:
non-unix endpoints, closed connections, wrong-owner connections, and the
bound() fence on non-unix endpoints.
"""

from __future__ import annotations

import os
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from agent_peer.backends.base import TransportEndpoint
from agent_peer.backends.posix import PosixTransportBackend, _frame
from agent_peer.errors import UnreachableError


class TestPosixBackendErrors:
    def test_request_non_unix_endpoint_rejected(self):
        backend = PosixTransportBackend()
        endpoint = TransportEndpoint(kind="tcp", address="127.0.0.1:1")
        with pytest.raises(UnreachableError):
            backend.request(endpoint, b"x", timeout=1)

    def test_bound_non_unix_endpoint_false(self):
        backend = PosixTransportBackend()
        endpoint = TransportEndpoint(kind="tcp", address="127.0.0.1:1")
        assert backend.bound(endpoint, timeout=0.2) is False

    def test_request_to_closed_socket_unreachable(self):
        # A listener that accepts then immediately closes: the client's
        # recv loop sees EOF and must raise UnreachableError, not hang.
        root = Path(tempfile.mkdtemp())
        sock_path = root / "closed.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)
        ready = threading.Event()
        closed = threading.Event()

        def serve() -> None:
            conn, _ = srv.accept()
            ready.set()
            conn.close()
            closed.set()

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        backend = PosixTransportBackend()
        endpoint = TransportEndpoint(kind="unix", address=str(sock_path))
        with pytest.raises(UnreachableError):
            backend.request(endpoint, _frame(b"ping"), timeout=2)
        closed.wait(2)
        srv.close()

    def test_request_wrong_owner_rejected(self):
        # SO_PEERCRED cannot be forged from the test process, but a
        # non-socket connection object must fail closed in the owner check.
        backend = PosixTransportBackend()
        evidence = backend.verify_remote_owner(object())  # type: ignore[arg-type]
        assert evidence.authenticated is False
        assert evidence.detail == "not a socket"

    def test_bound_unreachable_path_false(self):
        backend = PosixTransportBackend()
        endpoint = TransportEndpoint(
            kind="unix", address=f"/tmp/agent-peer-{os.getuid()}/no-such-sock-{os.getpid()}"
        )
        assert backend.bound(endpoint, timeout=0.2) is False

    def test_request_credential_fail_rejected(self, monkeypatch):
        """A socket whose peer credentials do not verify must be refused."""
        import agent_peer.backends.posix as posixmod

        monkeypatch.setattr(posixmod, "peer_credentials", lambda sock: {})
        backend = PosixTransportBackend()
        root = Path(tempfile.mkdtemp())
        sock_path = root / "cred.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)
        ready = threading.Event()

        def serve() -> None:
            srv.accept()
            ready.set()

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        endpoint = TransportEndpoint(kind="unix", address=str(sock_path))
        with pytest.raises(UnreachableError, match="credential"):
            backend.request(endpoint, _frame(b"ping"), timeout=2)
        ready.wait(2)
        srv.close()

    def test_request_clean_close_is_unreachable(self):
        """Server reads then closes cleanly: client recv sees EOF (not RST)
        and must raise UnreachableError."""
        root = Path(tempfile.mkdtemp())
        sock_path = root / "eof.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)
        done = threading.Event()

        def serve() -> None:
            conn, _ = srv.accept()
            conn.recv(4096)  # drain the frame
            conn.close()  # clean EOF, not reset
            done.set()

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        backend = PosixTransportBackend()
        endpoint = TransportEndpoint(kind="unix", address=str(sock_path))
        with pytest.raises(UnreachableError):
            backend.request(endpoint, _frame(b"ping"), timeout=2)
        done.wait(2)
        srv.close()

    def test_request_reply_iteration(self):
        """Server replies with a framed payload: the decoder feed loop
        yields the reply (happy-path branch)."""
        import agent_peer.backends.posix as posixmod

        root = Path(tempfile.mkdtemp())
        sock_path = root / "reply.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)
        done = threading.Event()

        def serve() -> None:
            conn, _ = srv.accept()
            conn.recv(4096)
            conn.sendall(posixmod._frame(b"pong"))
            conn.close()
            done.set()

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        backend = PosixTransportBackend()
        endpoint = TransportEndpoint(kind="unix", address=str(sock_path))
        reply = backend.request(endpoint, _frame(b"ping"), timeout=2)
        assert reply == b"pong"
        done.wait(2)
        srv.close()

    def test_verify_remote_owner_socket_foreign_uid(self, monkeypatch):
        """A socket whose credentials do not verify returns authenticated
        False with a same-UID detail string."""
        import agent_peer.backends.posix as posixmod

        monkeypatch.setattr(posixmod, "peer_credentials", lambda sock: {"uid": 9999})
        backend = PosixTransportBackend()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        evidence = backend.verify_remote_owner(sock)
        assert evidence.authenticated is False
        assert evidence.detail == "SO_PEERCRED foreign UID"
        sock.close()
