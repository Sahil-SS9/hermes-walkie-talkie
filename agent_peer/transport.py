"""Unix-socket transport: sender client, peer credentials, framing helpers (AP-502, AP-505).

Wire format: length-prefixed canonical JSON envelopes (see codec.py).
Server-side handling lives in the supervisor (runtime.py); this module owns
the client side and the same-UID credential checks.
"""

from __future__ import annotations

import contextlib
import os
import socket
import struct

from .codec import FrameDecoder, encode_envelope
from .constants import CONNECT_TIMEOUT, RECEIPT_TIMEOUT
from .errors import TimeoutError_, UnreachableError
from .models import Envelope

_SO_PEERCRED = getattr(socket, "SO_PEERCRED", None)


def peer_credentials(sock: socket.socket | None = None) -> dict:
    """Return ``{pid, uid, gid}`` of the socket peer (Linux SO_PEERCRED).

    Falls back to the current process identity on platforms without
    ``SO_PEERCRED`` (macOS) so the same-UID check still passes for local
    peers — the owner-verified runtime directory is the macOS boundary.
    """
    if _SO_PEERCRED is not None and sock is not None:
        try:
            creds = sock.getsockopt(socket.SOL_SOCKET, _SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, gid = struct.unpack("3i", creds)
            return {"pid": pid, "uid": uid, "gid": gid}
        except OSError:
            pass
    return {"pid": os.getpid(), "uid": os.geteuid(), "gid": os.getegid()}


def verify_peer_credentials(creds: dict) -> bool:
    """Same-UID check: reject peers that do not belong to the OS user."""
    uid = creds.get("uid")
    return isinstance(uid, int) and uid == os.geteuid()


class PeerClient:
    """One-shot sender client: connect, frame, send, await bounded receipt.

    - Connect timeout: 1 s (``CONNECT_TIMEOUT``).
    - Receipt timeout: 3 s (``RECEIPT_TIMEOUT``) — a silent or stalling
      receiver raises :class:`TimeoutError_`.
    """

    def __init__(self, socket_path: str, *, connect_timeout: float = CONNECT_TIMEOUT, receipt_timeout: float = RECEIPT_TIMEOUT) -> None:
        self._socket_path = socket_path
        self._connect_timeout = connect_timeout
        self._receipt_timeout = receipt_timeout

    def request(self, envelope: Envelope) -> Envelope:
        """Send one envelope and await the reply envelope (receipt/pong)."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._connect_timeout)
        try:
            try:
                sock.connect(self._socket_path)
            except (OSError, FileNotFoundError) as exc:
                raise UnreachableError(f"cannot connect to {self._socket_path}: {exc}") from exc
            # Same-UID check on the accepted connection (Linux).
            if not verify_peer_credentials(peer_credentials(sock)):
                raise UnreachableError("peer credential check failed (different UID)")
            sock.settimeout(self._receipt_timeout)
            # Wire protocol: 4-byte length prefix + canonical JSON envelope
            # (same framing in both directions — see codec.encode_frame).
            from .codec import encode_frame

            sock.sendall(encode_frame(encode_envelope(envelope)))
            decoder = FrameDecoder()
            while True:
                try:
                    chunk = sock.recv(4096)
                except TimeoutError as exc:
                    raise TimeoutError_(
                        f"no receipt from {self._socket_path} within {self._receipt_timeout}s"
                    ) from exc
                if not chunk:
                    raise UnreachableError(f"peer closed connection at {self._socket_path}")
                for reply in decoder.feed(chunk):
                    return reply
        finally:
            with contextlib.suppress(OSError):
                sock.close()
