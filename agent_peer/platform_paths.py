"""Platform path backend selection (plan G5.2, G5.5; P1.4/P1.5).

``auto`` selects by the ACTUAL platform at runtime — never by mocked
``sys.platform``. On POSIX the accepted XDG/chmod/st_uid policy is used; on
Windows the ``%LOCALAPPDATA%`` policy is used when a proven backend exists.
Backends raise ``NotImplementedError`` rather than returning fake paths.
"""

from __future__ import annotations

import sys
from typing import Protocol

from .backends import PathBackend


class _PathBackendFactory(Protocol):
    def __call__(self) -> PathBackend: ...


def _select_platform() -> str:
    """Actual platform classification (never mocked)."""
    return "win32" if sys.platform == "win32" else "posix"


def get_path_backend(*, platform: str | None = None) -> PathBackend:
    """Return the path backend for *platform* (default: actual platform).

    ``platform`` is accepted for explicit test injection only; production
    callers must omit it so the real platform drives selection.
    """
    platform = platform or _select_platform()
    if platform == "win32":
        from .backends.windows import WindowsPathBackend

        return WindowsPathBackend()
    from .backends.posix import PosixPathBackend

    return PosixPathBackend()


__all__ = ["PathBackend", "get_path_backend"]
