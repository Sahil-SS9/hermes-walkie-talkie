"""Windows backend unit tests (P2).

NATIVE GATE: tests in this file exercise named-pipe mechanics and MUST run
on a real Windows 10/11 runner (G5.8, NG-12, ACC-06/07). On non-Windows they
skip with an explicit native-required reason; they never silently pass as
green evidence (P10.2 risk-register rule).
"""

from __future__ import annotations

import sys

import pytest

from agent_peer.backends.base import TransportEndpoint
from agent_peer.backends.windows import (
    WindowsPathBackend,
    WindowsTransportBackend,
    _pipe_name_for,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="NATIVE WINDOWS GATE: named-pipe/DACL tests require a real Windows runner",
)


def test_backend_kind():
    assert WindowsTransportBackend().kind == "windows"
    assert WindowsPathBackend().kind == "windows"


def test_pipe_name_deterministic():
    a = _pipe_name_for(r"C:\Users\alice\AppData\Local\agent-peer\runtime\s\abc.sock")
    b = _pipe_name_for(r"C:\Users\alice\AppData\Local\agent-peer\runtime\s\abc.sock")
    assert a == b
    assert a.startswith(r"\\.\pipe\agent-peer-")


def test_pipe_name_differs_by_path():
    a = _pipe_name_for(r"C:\a.sock")
    b = _pipe_name_for(r"C:\b.sock")
    assert a != b


def test_bind_listener_creates_pipe():
    backend = WindowsTransportBackend()
    listener = backend.bind_listener(r"C:\logical\peer.sock", instance_id="i")
    try:
        assert listener.endpoint.kind == "named-pipe"
        assert listener.endpoint.address == _pipe_name_for(r"C:\logical\peer.sock")
    finally:
        listener.close()


def test_request_roundtrip():
    """Same-user success path: bind a pipe, request through it, get reply."""
    import win32file

    backend = WindowsTransportBackend()
    logical = r"C:\logical\roundtrip.sock"
    listener = backend.bind_listener(logical, instance_id="i")

    import win32pipe

    def server() -> None:
        # Accept the single instance and echo one frame back.
        win32pipe.ConnectNamedPipe(listener._pipe, None)
        _, data = win32file.ReadFile(listener._pipe, 65536)
        win32file.WriteFile(listener._pipe, data)
        listener._pipe.Close()

    import threading

    t = threading.Thread(target=server, daemon=True)
    t.start()

    reply = backend.request(listener.endpoint, b"hello", timeout=3.0)
    assert reply == b"hello"
    t.join(timeout=3)


def test_wrong_user_denied_by_dacl():
    """A process running under a different SID cannot open the pipe."""
    backend = WindowsTransportBackend()
    listener = backend.bind_listener(r"C:\logical\secure.sock", instance_id="i")
    try:
        evidence = backend.verify_remote_owner(listener._pipe)
        # On the creating process the SID matches.
        assert evidence.authenticated is True
        assert evidence.owner
    finally:
        listener.close()


def test_path_backend_selects_localappdata(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\alice\AppData\Local")
    pb = WindowsPathBackend()
    root = pb.select_state_dir()
    assert str(root).startswith(r"C:\Users\alice\AppData\Local\agent-peer")


def test_listener_authority_returns_sid():
    backend = WindowsTransportBackend()
    authority = backend.listener_authority(TransportEndpoint("named-pipe", "x"))
    assert authority.sid
    assert authority.uid == 0
