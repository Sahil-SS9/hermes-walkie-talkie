"""POSIX transport backend: AF_UNIX + SO_PEERCRED + chmod/st_uid (ADR-0005).

This is the REFERENCE backend for the backend-neutral contract. It wraps the
accepted V1 implementation (transport.py, paths.py) without changing its
behaviour: same framing, same same-UID checks, same resource ceilings, same
listener fencing. Conformance tests run against this backend on every
platform; the Windows backend must satisfy the same contract (P2).

Framing note: the backend contract operates on RAW PAYLOAD BYTES (no Envelope
knowledge). The 4-byte big-endian length prefix is applied here so the wire
format is identical to V1 (codec.FrameDecoder expects the same shape); the
caller (runtime/discovery) owns Envelope encode/decode.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import socket
from pathlib import Path

from ..constants import CONNECT_TIMEOUT, FRAME_LENGTH_PREFIX_BYTES, MAX_FRAME_BYTES, RECEIPT_TIMEOUT
from ..errors import OversizedError, TimeoutError_, UnreachableError
from ..transport import peer_credentials, verify_peer_credentials
from .base import ListenerAuthority, OwnerEvidence, TransportEndpoint

_MAX_SOCKET_PATH = 100  # safe bound under Linux sun_path=108

_OWNER_ONLY_FILE = 0o600


def _frame(payload: bytes) -> bytes:
    """Length-prefix raw payload bytes (4-byte big-endian)."""
    if len(payload) > MAX_FRAME_BYTES:
        raise OversizedError(
            f"frame payload {len(payload)} bytes exceeds {MAX_FRAME_BYTES}"
        )
    return len(payload).to_bytes(FRAME_LENGTH_PREFIX_BYTES, "big") + payload


class _RawFrameDecoder:
    """Incremental decoder yielding raw payload bytes (codec-neutral)."""

    __slots__ = ("_buffer", "_expected")

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._expected: int | None = None

    def feed(self, data: bytes):
        self._buffer.extend(data)
        while True:
            if self._expected is None:
                if len(self._buffer) < FRAME_LENGTH_PREFIX_BYTES:
                    return
                length = int.from_bytes(
                    bytes(self._buffer[:FRAME_LENGTH_PREFIX_BYTES]), "big"
                )
                if length > MAX_FRAME_BYTES:
                    raise OversizedError(
                        f"frame length {length} exceeds ceiling {MAX_FRAME_BYTES}"
                    )
                self._expected = length
                del self._buffer[:FRAME_LENGTH_PREFIX_BYTES]
            if len(self._buffer) < self._expected:
                return
            payload = bytes(self._buffer[: self._expected])
            del self._buffer[: self._expected]
            self._expected = None
            yield payload


def _socket_path_for(sockets_dir: Path, peer_id: str, instance_id: str | None = None) -> Path:
    """Deterministic short socket path bound to peer and live instance."""
    authority = f"{peer_id}\0{instance_id}" if instance_id else peer_id
    short = hashlib.sha256(authority.encode("utf-8")).hexdigest()[:16]
    return sockets_dir / f"{short}.sock"


class _PosixListener:
    """Listener handle exposing the raw bound socket to a supervisor loop."""

    def __init__(self, endpoint: TransportEndpoint, sock: socket.socket) -> None:
        self.endpoint = endpoint
        self._sock = sock

    def fileno(self) -> int:
        return self._sock.fileno()

    def accept(self) -> socket.socket:
        conn, _ = self._sock.accept()
        return conn

    def close(self) -> None:
        """Close FD and unlink the endpoint (normal teardown)."""
        with contextlib.suppress(OSError):
            self._sock.close()
        with contextlib.suppress(OSError):
            os.unlink(self.endpoint.address)

    def close_fd(self) -> None:
        """Close the FD only — replacement-fence path: never unlink."""
        with contextlib.suppress(OSError):
            self._sock.close()


class PosixTransportBackend:
    """Reference POSIX implementation of :class:`LocalTransportBackend`."""

    kind = "posix"

    def __init__(
        self,
        *,
        connect_timeout: float = CONNECT_TIMEOUT,
        receipt_timeout: float = RECEIPT_TIMEOUT,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._receipt_timeout = receipt_timeout

    def bind_listener(
        self,
        socket_path: Path,
        *,
        instance_id: str,
        on_frame=None,
    ) -> _PosixListener:
        """Bind an owner-only AF_UNIX listener at an explicit path.

        The path backend owns *where* (PosixPathBackend.socket_path_for);
        this backend owns the socket mechanics (bind, chmod 0600, listen,
        non-blocking). ``on_frame`` is the frame dispatch callback owned by
        the supervisor; the listener itself is passive.
        """
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(socket_path))
            os.chmod(socket_path, _OWNER_ONLY_FILE)
            sock.listen(64)
            sock.setblocking(False)
        except Exception:
            with contextlib.suppress(OSError):
                sock.close()
            with contextlib.suppress(OSError):
                socket_path.unlink()
            raise
        return _PosixListener(
            TransportEndpoint(kind="unix", address=str(socket_path)),
            sock,
        )

    def create_listener(self, *, instance_id: str, on_frame) -> _PosixListener:
        raise NotImplementedError(
            "use bind_listener with an explicit path from the path backend"
        )

    def request(self, endpoint: TransportEndpoint, frame: bytes, *, timeout: float) -> bytes:
        """Send one raw payload and await the reply payload (bounded)."""
        if endpoint.kind != "unix":
            raise UnreachableError(f"posix backend cannot address {endpoint.kind!r}")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._connect_timeout)
        try:
            try:
                sock.connect(endpoint.address)
            except (OSError, FileNotFoundError) as exc:
                raise UnreachableError(
                    f"cannot connect to {endpoint.address}: {exc}"
                ) from exc
            if not verify_peer_credentials(peer_credentials(sock)):
                raise UnreachableError("peer credential check failed (different UID)")
            sock.settimeout(timeout)
            sock.sendall(_frame(frame))
            decoder = _RawFrameDecoder()
            while True:
                try:
                    chunk = sock.recv(4096)
                except TimeoutError as exc:
                    raise TimeoutError_(
                        f"no reply from {endpoint.address} within {timeout}s"
                    ) from exc
                if not chunk:
                    raise UnreachableError(
                        f"peer closed connection at {endpoint.address}"
                    )
                for reply in decoder.feed(chunk):
                    return reply
        finally:
            with contextlib.suppress(OSError):
                sock.close()

    def probe(self, endpoint: TransportEndpoint, challenge: bytes, *, timeout: float) -> bytes:
        """Challenge-response over the raw transport (identity proof)."""
        return self.request(endpoint, b"PROBE:" + challenge, timeout=timeout)

    def bound(self, endpoint: TransportEndpoint, *, timeout: float) -> bool:
        """Connect-only liveness check (V1 ``_socket_bound`` fence)."""
        if endpoint.kind != "unix":
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(endpoint.address)
            return True
        except OSError:
            return False
        finally:
            with contextlib.suppress(OSError):
                s.close()

    def verify_remote_owner(self, connection: object) -> OwnerEvidence:
        """Same-UID proof via SO_PEERCRED (macOS falls back to self-identity)."""
        if isinstance(connection, socket.socket):
            creds = peer_credentials(connection)
            if verify_peer_credentials(creds):
                return OwnerEvidence(
                    owner=str(creds.get("uid", "")),
                    authenticated=True,
                    detail="SO_PEERCRED same-UID",
                )
            return OwnerEvidence(
                owner=str(creds.get("uid", "")),
                authenticated=False,
                detail="SO_PEERCRED foreign UID",
            )
        return OwnerEvidence(owner="", authenticated=False, detail="not a socket")

    def listener_authority(self, endpoint: TransportEndpoint) -> ListenerAuthority:
        """Capture st_uid/st_ino of the bound socket (REM-105 fence)."""
        try:
            st = Path(endpoint.address).stat()
        except OSError:
            return ListenerAuthority()
        return ListenerAuthority(uid=st.st_uid, inode=st.st_ino)

    def close(self) -> None:
        pass


class PosixPathBackend:
    """Owner-local path policy (XDG, chmod 0700/0600, st_uid checks)."""

    kind = "posix"

    def select_runtime_dir(self) -> Path:
        from ..paths import select_runtime_dir as _select

        return _select()

    def select_state_dir(self) -> Path:
        from ..paths import select_state_dir as _select

        return _select()

    def validate_runtime_dir(self, path: Path) -> Path:
        from ..paths import validate_runtime_dir as _validate

        return _validate(path)

    def socket_path_for(self, sockets_dir: Path, peer_id: str, instance_id: str | None = None) -> Path:
        return _socket_path_for(sockets_dir, peer_id, instance_id)


__all__ = [
    "PosixPathBackend",
    "PosixTransportBackend",
    "_RawFrameDecoder",
    "_frame",
    "_socket_path_for",
]
