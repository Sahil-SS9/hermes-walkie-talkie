"""Secure owner-local runtime and state paths (ADR-0001 §4.5, AP-401/402).

Rules:
- Runtime dirs are ``0700`` owner-only.
- Registry files, sockets and the SQLite DB are owner-only (``0600``).
- Symlinked or wrong-owner runtime paths are refused.
- Socket paths must stay short enough for ``AF_UNIX`` (bounded at 100).
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError

_MAX_SOCKET_PATH = 100  # safe bound under Linux sun_path=108

_OWNER_ONLY_DIR = 0o700
_OWNER_ONLY_FILE = 0o600


def _is_owner_only(path: Path, *, directory: bool) -> bool:
    try:
        st = path.stat()
    except OSError:
        return False
    if st.st_uid != os.geteuid():
        return False
    forbidden = 0o077 if directory else 0o077
    return (st.st_mode & forbidden) == 0


def validate_runtime_dir(path: Path) -> Path:
    """Validate (creating if needed) one owner-only runtime directory."""
    try:
        path.mkdir(mode=_OWNER_ONLY_DIR, parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(f"cannot create runtime dir {path}: {exc}") from exc
    if path.is_symlink():
        raise ConfigurationError(f"runtime dir must not be a symlink: {path}")
    if not _is_owner_only(path, directory=True):
        raise ConfigurationError(
            f"runtime dir must be owner-only (0700 or stricter): {path} "
            f"(mode={oct(stat.S_IMODE(path.stat().st_mode))})"
        )
    return path


def _candidate_from(xdg_runtime: str) -> Path:
    return Path(xdg_runtime) / "agent-peer"


def _fallback_root() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state_home) / "agent-peer" / "runtime"


def select_runtime_dir() -> Path:
    """Choose the owner-local agent-peer runtime root.

    Preference order:
    1. ``$XDG_RUNTIME_DIR/agent-peer`` when present, not a symlink and
       owner-only;
    2. an owner-verified short fallback under ``$XDG_STATE_HOME`` (or
       ``~/.local/state``) — never under a profile-specific HERMES_HOME.

    Explicit override ``AGENT_PEER_RUNTIME_DIR`` wins when provided (used by
    tests and disposable pilots); it is still validated.
    """
    override = os.environ.get("AGENT_PEER_RUNTIME_DIR")
    candidates: list[tuple[Path, Path | None]] = []  # (candidate, parent-to-verify)
    if override:
        candidates.append((Path(override), None))
    else:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            xdg_root = Path(xdg)
            candidates.append((xdg_root / "agent-peer", xdg_root))
        candidates.append((_fallback_root(), None))

    last_error: Exception | None = None
    for candidate, parent in candidates:
        try:
            if candidate.is_symlink():
                raise ConfigurationError(f"runtime dir must not be a symlink: {candidate}")
            if parent is not None:
                # The XDG runtime root itself must be owner-only and not a
                # symlink (XDG spec: 0700, owned by the user). Never create
                # or repair it — just verify.
                if parent.is_symlink():
                    raise ConfigurationError(f"runtime parent must not be a symlink: {parent}")
                if not _is_owner_only(parent, directory=True):
                    raise ConfigurationError(
                        f"runtime parent must be owner-only (0700 or stricter): {parent} "
                        f"(mode={oct(stat.S_IMODE(parent.stat().st_mode))})"
                    )
            return validate_runtime_dir(candidate)
        except ConfigurationError as exc:
            last_error = exc
            continue
    raise ConfigurationError(
        f"no secure runtime dir available: {last_error}"
    ) from last_error


def select_state_dir() -> Path:
    """Owner-local persistent state root (SQLite lives here)."""
    override = os.environ.get("AGENT_PEER_STATE_DIR")
    if override:
        root = Path(override)
    else:
        state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        root = Path(state_home) / "agent-peer"
    return validate_runtime_dir(root)


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Layout of the shared owner-local runtime root."""

    root: Path
    registry_dir: Path
    sockets_dir: Path

    def __init__(self, root: Path) -> None:
        object.__setattr__(self, "root", validate_runtime_dir(root))
        object.__setattr__(self, "registry_dir", validate_runtime_dir(root / "registry"))
        object.__setattr__(self, "sockets_dir", validate_runtime_dir(root / "sockets"))

    def registry_file_for(self, peer_id: str) -> Path:
        return self.registry_dir / f"{peer_id}.json"

    def socket_path_for(self, peer_id: str, *, must_be_short: bool = False) -> Path:
        path = self.sockets_dir / f"{peer_id}.sock"
        if must_be_short and len(str(path)) > _MAX_SOCKET_PATH:
            raise ConfigurationError(
                f"socket path too long ({len(str(path))} > {_MAX_SOCKET_PATH}): {path}"
            )
        return path

    @classmethod
    def select(cls) -> RuntimePaths:
        return cls(select_runtime_dir())
