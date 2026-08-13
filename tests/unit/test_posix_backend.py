"""POSIX backend unit tests (P1.3/P1.4, ADR-0005).

These cover backend-specific mechanics that the shared conformance surface
does not: framing bounds, socket path determinism, listener binding details,
and path backend selection.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_peer.backends.posix import (
    PosixPathBackend,
    PosixTransportBackend,
    _frame,
    _RawFrameDecoder,
    _socket_path_for,
)
from agent_peer.errors import OversizedError

# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


def test_frame_length_prefix():
    framed = _frame(b"hello")
    assert framed[:4] == (5).to_bytes(4, "big")
    assert framed[4:] == b"hello"


def test_frame_rejects_oversized():
    with pytest.raises(OversizedError):
        _frame(b"x" * (64 * 1024 + 1))


def test_raw_frame_decoder_yields_payloads():
    decoder = _RawFrameDecoder()
    framed = _frame(b"one") + _frame(b"two")
    out = list(decoder.feed(framed))
    assert out == [b"one", b"two"]


def test_raw_frame_decoder_incremental():
    decoder = _RawFrameDecoder()
    framed = _frame(b"abc")
    out = []
    for i in range(len(framed)):
        out.extend(decoder.feed(framed[i : i + 1]))
    assert out == [b"abc"]


def test_raw_frame_decoder_rejects_oversized_prefix():
    decoder = _RawFrameDecoder()
    with pytest.raises(OversizedError):
        list(decoder.feed((64 * 1024 + 1).to_bytes(4, "big")))


# ---------------------------------------------------------------------------
# Socket path determinism
# ---------------------------------------------------------------------------


def test_socket_path_is_deterministic():
    a = _socket_path_for(Path("/tmp/s"), "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    b = _socket_path_for(Path("/tmp/s"), "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    assert a == b
    assert a.name.endswith(".sock")
    assert len(a.name) == 16 + len(".sock")


def test_socket_path_differs_by_instance():
    a = _socket_path_for(Path("/tmp/s"), "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    b = _socket_path_for(Path("/tmp/s"), "11111111-1111-1111-1111-111111111111", "33333333-3333-3333-3333-333333333333")
    assert a != b


def test_socket_path_without_instance_uses_peer_only():
    a = _socket_path_for(Path("/tmp/s"), "11111111-1111-1111-1111-111111111111")
    b = _socket_path_for(Path("/tmp/s"), "11111111-1111-1111-1111-111111111111")
    assert a == b


# ---------------------------------------------------------------------------
# Listener binding
# ---------------------------------------------------------------------------


def test_bind_listener_creates_owner_only_socket(tmp_path):
    backend = PosixTransportBackend()
    path = tmp_path / "bind.sock"
    listener = backend.bind_listener(path, instance_id="x", on_frame=lambda f: None)
    try:
        assert path.exists()
        st = path.stat()
        assert st.st_uid == os.geteuid()
        assert (st.st_mode & 0o077) == 0
        # bound socket is non-blocking and listening
        assert listener.fileno() > 0
    finally:
        listener.close()


def test_bind_listener_failure_cleans_up(tmp_path):
    backend = PosixTransportBackend()
    # Binding to a directory path must fail and leave no partial state.
    path = tmp_path / "adir"
    path.mkdir()
    with pytest.raises(OSError):
        backend.bind_listener(path, instance_id="x", on_frame=lambda f: None)


def test_posix_path_backend_socket_path(tmp_path):
    pb = PosixPathBackend()
    p = pb.socket_path_for(tmp_path, "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    assert p.parent == tmp_path


def test_posix_backend_kind():
    assert PosixTransportBackend().kind == "posix"
    assert PosixPathBackend().kind == "posix"


def test_posix_backend_close_is_noop():
    PosixTransportBackend().close()
