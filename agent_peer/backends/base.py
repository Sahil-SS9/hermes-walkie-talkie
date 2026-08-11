"""Backend-neutral local IPC and path contracts (plan §3.2, ADR-0005).

These protocols are the seam between the harness-neutral core and the
platform transport. The accepted POSIX implementation (AF_UNIX + SO_PEERCRED
+ chmod/st_uid) must satisfy the same behavioural contract as the Windows
named-pipe backend. Backend stubs raise ``NotImplementedError``; they never
return fake empty success.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TransportEndpoint:
    """Opaque address of a local transport listener."""

    kind: str       # "unix" | "named-pipe" | ...
    address: str    # filesystem path (POSIX) or pipe name (Windows)


@dataclass(frozen=True, slots=True)
class OwnerEvidence:
    """Result of verifying the remote peer's OS identity."""

    owner: str           # canonical owner id (uid string / SID string)
    authenticated: bool  # true only after a real proof (SO_PEERCRED / DACL)
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ListenerAuthority:
    """Platform-specific fence captured from a bound listener.

    Used to refuse teardown/cleanup of a replaced or foreign listener
    (V1 REM-105/106/111 fence; Windows SID equivalent in P2).
    """

    uid: int = 0        # POSIX st_uid (0 on Windows)
    inode: int = 0      # POSIX st_ino (0 on Windows)
    sid: str = ""       # Windows SID string ("" on POSIX)


@runtime_checkable
class ListenerHandle(Protocol):
    """Live listener returned by ``create_listener``.

    ``fileno``/``accept`` expose the raw socket to a shared supervisor loop;
    ``close`` tears the listener down and unlinks the exact owned endpoint.
    ``close_fd`` closes the file descriptor WITHOUT touching the endpoint —
    used by the replacement fence (a path that is now owned by another live
    instance must never be unlinked, NG-15).
    """

    endpoint: TransportEndpoint

    def fileno(self) -> int: ...

    def accept(self) -> object: ...

    def close(self) -> None: ...

    def close_fd(self) -> None: ...


@runtime_checkable
class LocalTransportBackend(Protocol):
    """Platform transport contract (plan §3.2, ADR-0005)."""

    kind: str

    def create_listener(self, *, instance_id: str, on_frame: Callable) -> ListenerHandle: ...

    def bind_listener(self, socket_path, *, instance_id: str, on_frame: Callable | None = None) -> ListenerHandle:
        """Bind a listener at an explicit platform address.

        Production seam: the runtime must know the exact address (registry
        records and discovery carry ``socket_path``), so binding happens at
        an explicit path/pipe name rather than a backend-chosen one. POSIX
        binds an AF_UNIX socket; Windows binds a named pipe at the same
        logical address. ``on_frame`` is for backends that own their read
        loop (P2); the POSIX listener is passive — the supervisor owns
        dispatch.
        """
        ...

    def request(self, endpoint: TransportEndpoint, frame: bytes, *, timeout: float) -> bytes: ...

    def probe(self, endpoint: TransportEndpoint, challenge: bytes, *, timeout: float) -> bytes: ...

    def bound(self, endpoint: TransportEndpoint, *, timeout: float) -> bool:
        """True when a live listener is reachable at *endpoint*.

        Connect-only liveness (the V1 ``_socket_bound`` fence): a listener
        that accepts connections is live even when it rejects a malformed
        probe frame. Used by stale-repair fences; never mutates.
        """
        ...

    def verify_remote_owner(self, connection: object) -> OwnerEvidence: ...

    def listener_authority(self, endpoint: TransportEndpoint) -> ListenerAuthority: ...

    def close(self) -> None: ...


@runtime_checkable
class PathBackend(Protocol):
    """Owner-local runtime/state path policy (plan G5.2, G5.5)."""

    kind: str

    def select_runtime_dir(self) -> Path: ...

    def select_state_dir(self) -> Path: ...

    def validate_runtime_dir(self, path: Path) -> Path: ...

    def socket_path_for(self, sockets_dir: Path, peer_id: str, instance_id: str | None = None) -> Path: ...


__all__ = [
    "ListenerAuthority",
    "ListenerHandle",
    "LocalTransportBackend",
    "OwnerEvidence",
    "PathBackend",
    "TransportEndpoint",
]
