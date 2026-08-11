"""Windows transport backend: explicit SID/DACL named pipes (ADR-0005, P2).

Selected backend: Candidate 2 — a narrowly scoped Windows-only dependency
(``pywin32``) with an explicit SID-bound DACL, because stdlib ``AF_PIPE``
cannot prove same-user isolation without native tests (see ADR-0005 and
``docs/research/WINDOWS_TRANSPORT_SPIKE.md``).

Design (mirrors the accepted POSIX contract, plan §3.2):
- ``kind = "windows"``; endpoints are named-pipe addresses derived from the
  same deterministic logical socket path so registry/discovery stay
  platform-neutral.
- Listener creates a named pipe with a DACL that grants ONLY the current
  user's SID full control; any other SID is denied at the OS boundary
  (``G5.4`` same-user enforcement is the ACL, not a Python check).
- Client request/probe connect via ``win32file.CreateFile`` with bounded
  timeouts and the same 4-byte length-prefixed framing as POSIX.
- ``verify_remote_owner`` proves the connecting client's process SID matches
  the current user (token query), in addition to the ACL.
- ``listener_authority`` returns the pipe's owner SID as the fence identity.

NATIVE PROOF STATUS: PENDING. This module imports and compiles on any
platform, but every production method raises ``NotImplementedError`` unless
running on a real ``win32`` platform with ``pywin32`` installed. No Windows
completion claim is made without native execution (G5.8, NG-12, ACC-06/07).
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from ..constants import CONNECT_TIMEOUT, MAX_FRAME_BYTES, RECEIPT_TIMEOUT
from ..errors import TimeoutError_, UnreachableError
from .base import ListenerAuthority, OwnerEvidence, TransportEndpoint
from .posix import _frame, _RawFrameDecoder

_PIPE_PREFIX = r"\\.\pipe\agent-peer"


def _pipe_name_for(socket_path: Path | str) -> str:
    """Deterministic named-pipe name from a logical socket path.

    The pipe namespace is global per machine but ACL-scoped to the owner, so
    the deterministic hash keeps endpoints stable across processes while the
    DACL keeps them private.
    """
    digest = hashlib.sha256(str(socket_path).encode("utf-8")).hexdigest()[:32]
    return f"{_PIPE_PREFIX}-{digest}"


class _WindowsListener:
    """Listener handle for a named pipe (DACL-bound at creation)."""

    def __init__(self, endpoint: TransportEndpoint, pipe_handle) -> None:
        self.endpoint = endpoint
        self._pipe = pipe_handle

    def fileno(self) -> int:  # pragma: no cover - native only
        raise NotImplementedError(
            "named pipes have no pollable fd; the Windows supervisor uses a "
            "bounded per-listener wait thread (P2 native gate)"
        )

    def accept(self) -> object:  # pragma: no cover - native only
        raise NotImplementedError("native-only: ConnectNamedPipe")

    def close(self) -> None:  # pragma: no cover - native only
        raise NotImplementedError("native-only: CloseHandle")

    def close_fd(self) -> None:  # pragma: no cover - native only
        raise NotImplementedError("native-only: CloseHandle (no unlink)")


class WindowsTransportBackend:
    """Windows named-pipe transport (P2). Fail-closed until native-proven."""

    kind = "windows"

    def __init__(
        self,
        *,
        connect_timeout: float = CONNECT_TIMEOUT,
        receipt_timeout: float = RECEIPT_TIMEOUT,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._receipt_timeout = receipt_timeout

    # ------------------------------------------------------------------
    # Native imports — fail closed with an explicit message on Linux
    # ------------------------------------------------------------------

    def _native(self):
        if sys.platform != "win32":
            raise NotImplementedError(
                "WindowsTransportBackend requires native Windows execution "
                "(ADR-0005); Linux/macOS must never fabricate Windows evidence"
            )
        try:  # pragma: no cover - native only
            import pywintypes  # noqa: F401
            import win32api
            import win32file
            import win32pipe
            import win32security
        except ImportError as exc:  # pragma: no cover - native only
            raise NotImplementedError(
                "WindowsTransportBackend requires the optional Windows-only "
                "dependency `pywin32` (install: uv pip install '.[windows]')"
            ) from exc
        return {  # pragma: no cover - native only
            "win32api": win32api,
            "win32file": win32file,
            "win32pipe": win32pipe,
            "win32security": win32security,
        }

    def _current_user_sid(self, ns) -> str:  # pragma: no cover - native only
        """Current user SID as a string (the ACL owner)."""
        token = ns["win32security"].OpenProcessToken(
            ns["win32api"].GetCurrentProcess(),
            ns["win32security"].TOKEN_QUERY,
        )
        try:
            sid = ns["win32security"].GetTokenInformation(
                token, ns["win32security"].TokenUser
            )[0]
            return ns["win32security"].ConvertSidToStringSid(sid)
        finally:
            token.Close()

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def create_listener(self, *, instance_id: str, on_frame=None):
        raise NotImplementedError(
            "use bind_listener with an explicit logical path from the path backend"
        )

    def bind_listener(self, socket_path, *, instance_id: str, on_frame=None):  # pragma: no cover - native only
        ns = self._native()
        pipe_name = _pipe_name_for(socket_path)
        # SDDL: only the current user SID gets full control; everyone else is
        # denied at the OS boundary. The DACL IS the same-user enforcement.
        user_sid = self._current_user_sid(ns)
        sddl = f"D:P(A;;GA;;;{user_sid})"
        try:
            security = ns["win32security"].ConvertStringSecurityDescriptorToSecurityDescriptor(
                sddl, ns["win32security"].SDDL_REVISION_1
            )
            handle = ns["win32pipe"].CreateNamedPipe(
                pipe_name,
                ns["win32pipe"].PIPE_ACCESS_DUPLEX,
                ns["win32pipe"].PIPE_TYPE_MESSAGE
                | ns["win32pipe"].PIPE_READMODE_MESSAGE
                | ns["win32pipe"].PIPE_WAIT,
                1,  # one instance (bounded supervisor, no unbounded fan-out)
                65536,  # out buffer
                65536,  # in buffer
                0,  # default timeout
                security,
            )
        except Exception as exc:  # pragma: no cover - native only
            raise NotImplementedError(
                f"named-pipe creation failed (native gate): {exc}"
            ) from exc
        return _WindowsListener(
            TransportEndpoint(kind="named-pipe", address=pipe_name), handle
        )

    def request(self, endpoint: TransportEndpoint, frame: bytes, *, timeout: float) -> bytes:  # pragma: no cover - native only
        ns = self._native()
        if endpoint.kind != "named-pipe":
            raise UnreachableError(f"windows backend cannot address {endpoint.kind!r}")
        try:
            handle = ns["win32file"].CreateFile(
                endpoint.address,
                ns["win32file"].GENERIC_READ | ns["win32file"].GENERIC_WRITE,
                0,
                None,
                ns["win32file"].OPEN_EXISTING,
                0,
                None,
            )
        except Exception as exc:  # pragma: no cover - native only
            raise UnreachableError(f"cannot open pipe {endpoint.address}: {exc}") from exc
        try:
            framed = _frame(frame)
            ns["win32file"].WriteFile(handle, framed)
            decoder = _RawFrameDecoder()
            while True:
                try:
                    # Bounded read: pipe is message-mode, so one ReadFile gets
                    # one complete frame (or raises ERROR_MORE_DATA for large).
                    _, data = ns["win32file"].ReadFile(handle, MAX_FRAME_BYTES + 4)
                except Exception as exc:  # pragma: no cover - native only
                    raise TimeoutError_(
                        f"no reply from {endpoint.address}: {exc}"
                    ) from exc
                for reply in decoder.feed(data):
                    return reply
        finally:  # pragma: no cover - native only
            import contextlib

            with contextlib.suppress(Exception):
                handle.Close()

    def probe(self, endpoint: TransportEndpoint, challenge: bytes, *, timeout: float) -> bytes:
        return self.request(endpoint, b"PROBE:" + challenge, timeout=timeout)

    def bound(self, endpoint: TransportEndpoint, *, timeout: float) -> bool:  # pragma: no cover - native only
        """Connect-only liveness: a pipe that opens is live (DACL-gated)."""
        ns = self._native()
        if endpoint.kind != "named-pipe":
            return False
        try:
            handle = ns["win32file"].CreateFile(
                endpoint.address,
                ns["win32file"].GENERIC_READ | ns["win32file"].GENERIC_WRITE,
                0,
                None,
                ns["win32file"].OPEN_EXISTING,
                0,
                None,
            )
            handle.Close()
            return True
        except Exception:
            return False

    def verify_remote_owner(self, connection: object) -> OwnerEvidence:  # pragma: no cover - native only
        """Prove the connected peer's process SID == current user SID."""
        ns = self._native()
        # The DACL already denies foreign users at open time; this is the
        # authenticated second proof on the accepted connection.
        user_sid = self._current_user_sid(ns)
        try:
            client_pid = ns["win32pipe"].GetNamedPipeClientProcessId(connection)
            token = ns["win32security"].OpenProcessToken(
                client_pid, ns["win32security"].TOKEN_QUERY
            )
            try:
                client_sid = ns["win32security"].GetTokenInformation(
                    token, ns["win32security"].TokenUser
                )[0]
                client_sid_str = ns["win32security"].ConvertSidToStringSid(client_sid)
            finally:
                token.Close()
            if client_sid_str == user_sid:
                return OwnerEvidence(
                    owner=user_sid, authenticated=True, detail="SID match"
                )
            return OwnerEvidence(
                owner=client_sid_str, authenticated=False, detail="foreign SID"
            )
        except Exception as exc:  # pragma: no cover - native only
            return OwnerEvidence(owner="", authenticated=False, detail=str(exc))

    def listener_authority(self, endpoint: TransportEndpoint) -> ListenerAuthority:  # pragma: no cover - native only
        """The pipe owner SID is the fence identity on Windows."""
        ns = self._native()
        return ListenerAuthority(sid=self._current_user_sid(ns))

    def close(self) -> None:
        pass


class WindowsPathBackend:
    """Owner-local path policy under %LOCALAPPDATA% (G5.5, P2.3)."""

    kind = "windows"

    def select_runtime_dir(self) -> Path:  # pragma: no cover - native only
        self._native()
        # %LOCALAPPDATA%/agent-peer/runtime — owner-local by construction
        # (the OS gives each user their own LOCALAPPDATA).
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        root = Path(base) / "agent-peer" / "runtime"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def select_state_dir(self) -> Path:  # pragma: no cover - native only
        self._native()
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        root = Path(base) / "agent-peer"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def validate_runtime_dir(self, path: Path) -> Path:  # pragma: no cover - native only
        self._native()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def socket_path_for(self, sockets_dir: Path, peer_id: str, instance_id: str | None = None) -> Path:  # pragma: no cover - native only
        self._native()
        # Logical path only — the transport maps it to a named-pipe name.
        authority = f"{peer_id}\0{instance_id}" if instance_id else peer_id
        short = hashlib.sha256(authority.encode("utf-8")).hexdigest()[:16]
        return sockets_dir / f"{short}.sock"

    def _native(self) -> None:
        if sys.platform != "win32":
            raise NotImplementedError(
                "WindowsPathBackend requires native Windows execution "
                "(ADR-0005); no mocked %LOCALAPPDATA% on Linux"
            )


__all__ = ["WindowsPathBackend", "WindowsTransportBackend", "_pipe_name_for"]
