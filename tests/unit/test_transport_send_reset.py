"""Transport send-reset fail-closed (P11.3 adversarial probe).

A peer that accepts then immediately closes can reset the client's
sendall. That must surface as UnreachableError (observable, fail-closed),
never as an untyped ConnectionResetError leaking out of the transport.
"""

from __future__ import annotations

import socket
import tempfile
import threading
from pathlib import Path

import pytest

from agent_peer.errors import UnreachableError
from agent_peer.models import Kind, PeerIdentity, make_envelope
from agent_peer.transport import PeerClient

SENDER = PeerIdentity(peer_id="11111111-1111-4111-8111-111111111111")
RECIP = "22222222-2222-4222-8222-222222222222"


def test_send_to_immediately_closed_peer_is_unreachable():
    root = Path(tempfile.mkdtemp())
    sock_path = root / "rst.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    srv.listen(1)
    accepted = threading.Event()

    def close_immediately() -> None:
        conn, _ = srv.accept()
        accepted.set()
        conn.close()  # reset the client's pending send

    t = threading.Thread(target=close_immediately, daemon=True)
    t.start()
    client = PeerClient(str(sock_path), connect_timeout=2.0, receipt_timeout=2.0)
    env = make_envelope(
        sender=SENDER,
        recipient_peer_id=RECIP,
        kind=Kind.MESSAGE,
        content="ping",
    )
    # Either the send or the recv path must produce UnreachableError;
    # no ConnectionResetError or other bare OSError may escape.
    with pytest.raises(UnreachableError):
        client.request(env)
    accepted.wait(2)
    srv.close()
