"""Windows transport backend: fail-closed skeleton (P1) → native P2.

Per ADR-0005 and plan P2: this module is implemented with the explicit
SID-bound DACL named-pipe approach and MUST NOT be claimed as Windows
completion without native proof (G5.8, NG-12). Until the native Windows
backend is proven on a real runner, every production entry point here is
fail-closed: it raises rather than returning fake empty success.
"""

from __future__ import annotations

from pathlib import Path

from .base import ListenerAuthority, OwnerEvidence, TransportEndpoint


class WindowsTransportBackend:
    """Windows named-pipe transport (P2). Fail-closed until native-proven."""

    kind = "windows"

    def create_listener(self, *, instance_id: str, on_frame):
        raise NotImplementedError(
            "WindowsTransportBackend requires native Windows proof (ADR-0005); "
            "no mocked success is returned on Linux"
        )

    def bind_listener(self, socket_path, *, instance_id: str, on_frame=None):
        raise NotImplementedError(
            "WindowsTransportBackend requires native Windows proof (ADR-0005)"
        )

    def request(self, endpoint: TransportEndpoint, frame: bytes, *, timeout: float) -> bytes:
        raise NotImplementedError(
            "WindowsTransportBackend requires native Windows proof (ADR-0005)"
        )

    def probe(self, endpoint: TransportEndpoint, challenge: bytes, *, timeout: float) -> bytes:
        raise NotImplementedError(
            "WindowsTransportBackend requires native Windows proof (ADR-0005)"
        )

    def bound(self, endpoint: TransportEndpoint, *, timeout: float) -> bool:
        raise NotImplementedError(
            "WindowsTransportBackend requires native Windows proof (ADR-0005)"
        )

    def verify_remote_owner(self, connection: object) -> OwnerEvidence:
        raise NotImplementedError(
            "WindowsTransportBackend requires native Windows proof (ADR-0005)"
        )

    def listener_authority(self, endpoint: TransportEndpoint) -> ListenerAuthority:
        raise NotImplementedError(
            "WindowsTransportBackend requires native Windows proof (ADR-0005)"
        )

    def close(self) -> None:
        pass


class WindowsPathBackend:
    """Owner-local path policy under %LOCALAPPDATA% (G5.5). Fail-closed."""

    kind = "windows"

    def select_runtime_dir(self) -> Path:
        raise NotImplementedError(
            "WindowsPathBackend requires native Windows proof (ADR-0005)"
        )

    def select_state_dir(self) -> Path:
        raise NotImplementedError(
            "WindowsPathBackend requires native Windows proof (ADR-0005)"
        )

    def validate_runtime_dir(self, path: Path) -> Path:
        raise NotImplementedError(
            "WindowsPathBackend requires native Windows proof (ADR-0005)"
        )

    def socket_path_for(self, sockets_dir: Path, peer_id: str, instance_id: str | None = None) -> Path:
        raise NotImplementedError(
            "WindowsPathBackend requires native Windows proof (ADR-0005)"
        )


__all__ = ["WindowsPathBackend", "WindowsTransportBackend"]
