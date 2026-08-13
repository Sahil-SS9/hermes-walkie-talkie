"""Backend-neutral transport contract conformance (P1.1, ADR-0005).

The same behavioural contract MUST pass against the POSIX reference backend
(on every platform) and the Windows backend (on native Windows). This module
is the shared conformance surface: any backend that satisfies these tests
satisfies the transport contract.

Framing is raw-payload: callers send unframed bytes; the backend applies the
4-byte length prefix and returns unframed reply bytes (V1 wire format).
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from agent_peer.backends.base import TransportEndpoint
from agent_peer.backends.posix import PosixTransportBackend
from agent_peer.errors import TimeoutError_, UnreachableError


def _echo_server(backend: PosixTransportBackend, path: Path, *, echo: bool = True):
    """Minimal blocking echo listener proving the request/probe roundtrip.

    Uses a raw socket (not ``backend.bind_listener``) so the listener
    contract itself is exercised by its own dedicated tests.
    """
    lsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    lsock.bind(str(path))
    os.chmod(path, 0o600)
    lsock.listen(1)

    def serve() -> None:
        conn, _ = lsock.accept()
        try:
            while True:
                header = conn.recv(4)
                if not header:
                    return
                length = int.from_bytes(header, "big")
                payload = b""
                while len(payload) < length:
                    chunk = conn.recv(length - len(payload))
                    if not chunk:
                        return
                    payload += chunk
                if echo:
                    conn.sendall(header + payload)
        finally:
            conn.close()
            lsock.close()
            with contextlib.suppress(OSError):
                path.unlink()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    time.sleep(0.05)  # allow bind
    return None


@pytest.fixture()
def posix_backend() -> PosixTransportBackend:
    return PosixTransportBackend()


@pytest.fixture()
def sock_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sockets"
    d.mkdir()
    return d


def _endpoint_for(sock_dir: Path, peer_id: str) -> TransportEndpoint:
    return TransportEndpoint(kind="unix", address=str(sock_dir / f"{peer_id}.sock"))


# ---------------------------------------------------------------------------
# Contract: request/reply
# ---------------------------------------------------------------------------


def test_request_roundtrip_returns_reply_payload(posix_backend, sock_dir):
    path = sock_dir / "peer-a.sock"
    _echo_server(posix_backend, path)
    endpoint = _endpoint_for(sock_dir, "peer-a")

    reply = posix_backend.request(endpoint, b"hello", timeout=1.0)

    assert reply == b"hello"


def test_request_unknown_endpoint_fails_closed(posix_backend, sock_dir):
    endpoint = TransportEndpoint(kind="unix", address=str(sock_dir / "missing.sock"))

    with pytest.raises(UnreachableError):
        posix_backend.request(endpoint, b"x", timeout=0.5)


def test_request_timeout_fails_closed(posix_backend, sock_dir):
    """A listener that accepts but never replies must raise TimeoutError_."""
    path = sock_dir / "silent.sock"
    lsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    lsock.bind(str(path))
    lsock.listen(1)
    endpoint = TransportEndpoint(kind="unix", address=str(path))

    def silent() -> None:
        conn, _ = lsock.accept()
        try:
            time.sleep(2)
        finally:
            conn.close()

    thread = threading.Thread(target=silent, daemon=True)
    thread.start()
    time.sleep(0.05)

    with pytest.raises(TimeoutError_):
        posix_backend.request(endpoint, b"ping", timeout=0.3)


# ---------------------------------------------------------------------------
# Contract: probe
# ---------------------------------------------------------------------------


def test_probe_roundtrip(posix_backend, sock_dir):
    path = sock_dir / "peer-b.sock"
    _echo_server(posix_backend, path)
    endpoint = _endpoint_for(sock_dir, "peer-b")

    reply = posix_backend.probe(endpoint, b"challenge", timeout=1.0)

    assert reply == b"PROBE:challenge"


# ---------------------------------------------------------------------------
# Contract: owner verification
# ---------------------------------------------------------------------------


def test_verify_remote_owner_rejects_non_socket(posix_backend):
    evidence = posix_backend.verify_remote_owner(object())
    assert evidence.authenticated is False


def test_verify_remote_owner_same_uid_socket(posix_backend, sock_dir):
    """A live local socket connection must prove same-UID ownership."""
    path = sock_dir / "peer-c.sock"
    _echo_server(posix_backend, path)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(path))
        evidence = posix_backend.verify_remote_owner(sock)
        assert evidence.authenticated is True
        assert evidence.owner == str(os.geteuid())
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Contract: listener authority (fence)
# ---------------------------------------------------------------------------


def test_listener_authority_captures_uid_inode(posix_backend, sock_dir):
    path = sock_dir / "peer-d.sock"
    _echo_server(posix_backend, path)
    endpoint = _endpoint_for(sock_dir, "peer-d")

    authority = posix_backend.listener_authority(endpoint)

    assert authority.uid == os.geteuid()
    assert authority.inode > 0


def test_listener_authority_missing_endpoint_is_empty(posix_backend, sock_dir):
    endpoint = TransportEndpoint(kind="unix", address=str(sock_dir / "nope.sock"))
    authority = posix_backend.listener_authority(endpoint)
    assert authority.uid == 0
    assert authority.inode == 0


# ---------------------------------------------------------------------------
# Contract: teardown
# ---------------------------------------------------------------------------


def test_listener_close_unlinks_exact_path(posix_backend, sock_dir):
    path = sock_dir / "peer-e.sock"
    listener = posix_backend.bind_listener(path, instance_id="peer-e", on_frame=lambda f: None)
    assert path.exists()

    listener.close()

    assert not path.exists()


def test_windows_backend_stub_fails_closed():
    """The Windows backend must NOT return fake success before native proof."""
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = WindowsTransportBackend()
    with pytest.raises(NotImplementedError):
        backend.create_listener(instance_id="x", on_frame=lambda f: None)
    with pytest.raises(NotImplementedError):
        backend.request(TransportEndpoint("named-pipe", "x"), b"x", timeout=1.0)
    with pytest.raises(NotImplementedError):
        backend.verify_remote_owner(object())
    with pytest.raises(NotImplementedError):
        backend.listener_authority(TransportEndpoint("named-pipe", "x"))
