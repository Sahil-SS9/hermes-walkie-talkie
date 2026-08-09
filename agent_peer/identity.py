"""Peer identity generation, host metadata and alias persistence (AP-403)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .errors import ValidationError

_ALIAS_RE = None  # validated lazily


def generate_peer_id() -> str:
    """Immutable UUID for one live peer registration."""
    return str(uuid.uuid4())


def generate_instance_id() -> str:
    """Random UUID for one process incarnation (PID-reuse protection)."""
    return str(uuid.uuid4())


def _git_metadata(cwd: str) -> dict:
    """Best-effort git repo root + branch; never raises."""
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, timeout=3,
        )
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=3,
        )
        repo_root = root.stdout.strip() if root.returncode == 0 else ""
        branch_name = branch.stdout.strip() if branch.returncode == 0 else ""
        return {"git_repo_root": repo_root, "git_branch": branch_name}
    except Exception:
        return {"git_repo_root": "", "git_branch": ""}


def host_metadata(cwd: str | None = None) -> dict:
    """Stable host metadata: cwd, hostname, pid, started_at, git info."""
    cwd = cwd or os.getcwd()
    meta: dict = {
        "cwd": cwd,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
        "git_repo_root": "",
        "git_branch": "",
    }
    meta.update(_git_metadata(cwd))
    return meta


def default_name(cwd: str, peer_id: str) -> str:
    """``<repo-or-cwd>-<short-id>`` default alias (plan §4.1)."""
    base = os.path.basename(os.path.normpath(cwd)) or "session"
    return f"{base}-{peer_id[:6]}"


def _validate_alias(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("alias must not be empty")
    if len(name) > 64:
        raise ValidationError("alias must be at most 64 characters")
    if any(ch.isspace() for ch in name) or "/" in name or "\\" in name:
        raise ValidationError("alias must be a single word without path separators")
    if name.startswith("-"):
        raise ValidationError("alias must not start with '-'")
    return name


class AliasStore:
    """Persistent explicit aliases: peer_id -> human-readable name."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = __import__("threading").RLock()

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    def set_alias(self, peer_id: str, name: str) -> None:
        name = _validate_alias(name)
        with self._lock:
            data = self._load()
            data[peer_id] = name
            self._save(data)

    def get_alias(self, peer_id: str) -> str | None:
        with self._lock:
            return self._load().get(peer_id)

    def effective_name(self, peer_id: str, default_base: str) -> str:
        """The explicit alias when set, otherwise the derived default."""
        alias = self.get_alias(peer_id)
        return alias if alias else default_name(default_base, peer_id)
