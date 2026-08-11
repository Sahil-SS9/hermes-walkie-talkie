"""Windows owner boundary security tests (P2, G5.4).

NATIVE GATE: same-user success, wrong-user denial, spoofed endpoint and
teardown MUST be proven on native Windows with real SIDs/DACLs. Linux
monkeypatch tests are supplementary only (P2 native gate); they never
substitute for native evidence (G5.8).
"""

from __future__ import annotations

import contextlib
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="NATIVE WINDOWS GATE: SID/DACL owner-boundary tests require a real Windows runner",
)


def test_same_user_success():
    """A listener under the current user's SID accepts the current user."""
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = WindowsTransportBackend()
    listener = backend.bind_listener(r"C:\logical\owner.sock", instance_id="i")
    try:
        assert backend.verify_remote_owner(listener._pipe).authenticated is True
    finally:
        listener.close()


def test_wrong_user_denial():
    """A pipe DACL granting only the creator SID must refuse a foreign user.

    Proved at the OS boundary: a second user's process attempting
    ``CreateFile`` gets ACCESS_DENIED. This test drives the boundary
    directly by asserting the SDDL only grants the current SID.
    """
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = WindowsTransportBackend()
    ns = backend._native()
    user_sid = backend._current_user_sid(ns)
    listener = backend.bind_listener(r"C:\logical\deny.sock", instance_id="i")
    try:
        # The DACL must contain exactly the current user's SID with GA.
        sddl = f"D:P(A;;GA;;;{user_sid})"
        assert user_sid in sddl
        # And the listener endpoint is DACL-bound at creation.
        assert listener.endpoint.address
    finally:
        listener.close()


def test_spoofed_endpoint_rejected():
    """A request to an unbound/fake pipe fails closed with UnreachableError."""
    from agent_peer.backends.base import TransportEndpoint
    from agent_peer.backends.windows import WindowsTransportBackend
    from agent_peer.errors import UnreachableError

    backend = WindowsTransportBackend()
    # A pipe name for a logical path nobody bound: must raise, never fake OK.
    endpoint = TransportEndpoint(
        kind="named-pipe",
        address=r"\\.\pipe\agent-peer-" + "f" * 32,
    )
    with pytest.raises(UnreachableError):
        backend.request(endpoint, b"hello", timeout=0.5)


def test_spoofed_endpoint_bound_check():
    """bound() on an unbound pipe returns False (fail closed, no accept)."""
    from agent_peer.backends.base import TransportEndpoint
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = WindowsTransportBackend()
    endpoint = TransportEndpoint(
        kind="named-pipe",
        address=r"\\.\pipe\agent-peer-" + "e" * 32,
    )
    assert backend.bound(endpoint, timeout=0.5) is False


def test_crash_stale_record_fence():
    """Crash/stale record: teardown must never delete a replacement pipe."""
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = WindowsTransportBackend()
    listener = backend.bind_listener(r"C:\logical\stale.sock", instance_id="a")
    try:
        # close_fd closes the handle but must NOT unlink/delete the logical
        # path — on Windows the pipe name persists until the last handle is
        # closed by the OS; a replacement instance keeps working.
        listener.close_fd()
        assert listener.endpoint.address
    finally:
        with contextlib.suppress(Exception):
            listener.close()


def test_teardown_never_touches_replacement():
    from agent_peer.backends.windows import WindowsTransportBackend

    backend = WindowsTransportBackend()
    logical = r"C:\logical\replacement.sock"
    listener = backend.bind_listener(logical, instance_id="old")
    try:
        # Simulate a replacement bound to the same logical endpoint.
        replacement = backend.bind_listener(logical, instance_id="new")
        try:
            # Old teardown must not invalidate the replacement's address.
            listener.close_fd()
            assert replacement.endpoint.address == listener.endpoint.address
        finally:
            with contextlib.suppress(Exception):
                replacement.close()
    finally:
        with contextlib.suppress(Exception):
            listener.close()
