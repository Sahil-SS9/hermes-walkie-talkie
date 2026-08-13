"""Backend-neutral local transport and path backends (ADR-0005)."""

import sys

from .base import (
    ListenerAuthority,
    ListenerHandle,
    LocalTransportBackend,
    OwnerEvidence,
    PathBackend,
    TransportEndpoint,
)


def get_transport_backend(*, platform: str | None = None) -> LocalTransportBackend:
    """Return the transport backend for *platform* (default: actual platform).

    ``platform`` is accepted for explicit test injection only; production
    callers must omit it so the real platform drives selection (P1.5).
    """
    platform = platform or sys.platform
    if platform == "win32":
        from .windows import WindowsTransportBackend

        return WindowsTransportBackend()
    from .posix import PosixTransportBackend

    return PosixTransportBackend()


__all__ = [
    "ListenerAuthority",
    "ListenerHandle",
    "LocalTransportBackend",
    "OwnerEvidence",
    "PathBackend",
    "TransportEndpoint",
    "get_transport_backend",
]
