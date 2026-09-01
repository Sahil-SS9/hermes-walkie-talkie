"""Cross-platform PID-liveness probing (C-1, 2026-09-01 audit).

The historical liveness primitive was ``os.kill(pid, 0)``. That is correct on
POSIX (signal 0 performs an existence check only) but LETHAL on Windows:
CPython's Windows ``os.kill`` routes any signal that is not CTRL_C_EVENT /
CTRL_BREAK_EVENT through TerminateProcess, and sig 0 collides with
CTRL_C_EVENT at the C level (bpo-14484; the host repo documents the same
footgun in ``gateway/status.py::_pid_exists``). The walkie-talkie presence
poll executed that primitive against every other registered peer's PID —
every ambient surface (prompt pill, TUI bar, dashboard) killed the peer fleet
on each repaint. This is the single replacement primitive for every
PID-liveness need in the plugin (``hermes_peer.sessions._pid_alive``,
``agent_peer.registry.prune`` handshake wiring, any future caller).

Semantics (platform-independent contract):
- pid is falsy or <= 0      -> False
- process exists            -> True
- process does not exist    -> False
- exists but probe refused on POSIX (PermissionError) -> True
- any other OS error        -> False (fail closed; the caller treats the
  record as dead-ish, which only affects display classification).
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("agent_peer.pid_liveness")

_IS_WINDOWS = os.name == "nt" or sys.platform == "win32"


def _pid_alive_posix(pid: int) -> bool:
    """POSIX signal-0 existence probe (never terminates the target)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user: alive by definition.
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    """Windows existence probe that NEVER signals the target.

    Uses OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE) +
    WaitForSingleObject(handle, 0): WAIT_TIMEOUT means the process is still
    running; WAIT_OBJECT_0 means it has exited. This is a query-only path —
    unlike ``os.kill`` it cannot terminate the target, even if the handle
    carries the terminate right.
    """
    import ctypes

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        # Non-Windows interpreter exercising this branch (tests): report
        # not-alive rather than raising. Callers treat False as dead.
        logger.debug("pid_alive: ctypes.windll unavailable on this platform")
        return False

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    INVALID_HANDLE_VALUE = -1  # as returned for some bad opens

    try:
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid)
        )
    except OSError:  # pragma: no cover - defensive
        return False
    if not handle or handle == INVALID_HANDLE_VALUE:
        return False  # no handle == no such process (or no rights)
    try:
        wait = kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0)
        # WAIT_OBJECT_0 (0) -> signaled -> exited; WAIT_TIMEOUT -> alive.
        return wait == WAIT_TIMEOUT
    except OSError:  # pragma: no cover - defensive
        return False
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def pid_alive(pid: int | None) -> bool:
    """True when *pid* is a live process — Windows-safe (never kills).

    Replacement for the raw ``os.kill(pid, 0)`` probe. On POSIX this is the
    classic signal-0 check; on Windows it routes through the Win32 query API.
    """
    if not pid or int(pid) <= 0:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if _IS_WINDOWS:
        return _pid_alive_windows(pid)
    return _pid_alive_posix(pid)


__all__ = ["pid_alive"]
