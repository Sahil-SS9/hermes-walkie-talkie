"""Owner-local peer registry: atomic writes, presence, reachability, cleanup (AP-404..AP-411).

Design rules:
- One JSON file per peer (``registry/<peer_id>.json``), written atomically
  (temp file + fsync + ``os.replace``, mode ``0600``).
- Heartbeat timestamps are hints; socket handshakes are authoritative
  (P5). ``prune`` removes a file ONLY when the entry is stale AND the
  caller's handshake reports the instance dead — a live PID is never proof
  of identity without the matching instance (AP-407/408).
- Duplicate names are allowed and reported; exact peer_id is the
  deterministic tiebreaker (AP-409).
- The registry root is shared by all profiles under the same UID, so
  discovery is cross-profile by construction (AP-410).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .constants import STALE_THRESHOLD
from .models import PeerRecord, Presence
from .paths import RuntimePaths

logger = logging.getLogger("agent_peer.registry")

HandshakeCheck = Callable[[int, str], bool]  # (pid, instance_id) -> alive?


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class Registry:
    """Owner-local peer registry with atomic per-peer records."""

    def __init__(self, runtime_root: Path | RuntimePaths) -> None:
        self._paths = runtime_root if isinstance(runtime_root, RuntimePaths) else RuntimePaths(runtime_root)
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    def register(self, record: PeerRecord) -> None:
        """Write (or atomically update) one peer record."""
        with self._lock:
            data = {
                "peer_id": record.peer_id,
                "instance_id": record.instance_id,
                "session_id": record.session_id,
                "name": record.name,
                "profile": record.profile,
                "surface": record.surface,
                "host_target": record.host_target,
                "pid": record.pid,
                "cwd": record.cwd,
                "git_repo_root": record.git_repo_root,
                "git_branch": record.git_branch,
                "started_at": record.started_at or _now_iso(),
                "last_seen": record.last_seen or _now_iso(),
                "status": record.status,
                "socket_path": record.socket_path,
            }
            self._atomic_write(self._paths.registry_file_for(record.peer_id), data)

    def unregister(self, peer_id: str) -> bool:
        """Remove exactly this peer's record file. Returns True when removed."""
        with self._lock:
            path = self._paths.registry_file_for(peer_id)
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return False

    # -- presence ----------------------------------------------------------

    def update_presence(self, peer_id: str, status: Presence | str) -> None:
        import dataclasses

        status = status.value if isinstance(status, Presence) else status
        with self._lock:
            record = self.get(peer_id)
            if record is None:
                return
            self.register(
                dataclasses.replace(record, status=status, last_seen=_now_iso())
            )

    def heartbeat(self, peer_id: str) -> None:
        """Bounded heartbeat write: only refreshes last_seen."""
        import dataclasses

        with self._lock:
            record = self.get(peer_id)
            if record is None:
                return
            self.register(dataclasses.replace(record, last_seen=_now_iso()))

    # -- reads -------------------------------------------------------------

    def get(self, peer_id: str) -> PeerRecord | None:
        path = self._paths.registry_file_for(peer_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            return PeerRecord(**data)
        except Exception:
            logger.debug("skipping corrupt registry entry %s", path)
            return None

    def list_peers(self) -> list[PeerRecord]:
        records: list[PeerRecord] = []
        with self._lock:
            for path in sorted(self._paths.registry_dir.glob("*.json")):
                record = self._read_file(path)
                if record is not None:
                    records.append(record)
        return records

    def _read_file(self, path: Path) -> PeerRecord | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            return PeerRecord(**data)
        except Exception:
            logger.debug("skipping corrupt registry entry %s", path)
            return None

    # -- reachability ------------------------------------------------------

    def is_fresh(self, peer_id: str, now: datetime | None = None) -> bool:
        record = self.get(peer_id)
        if record is None:
            return False
        seen = _parse_iso(record.last_seen)
        if seen is None:
            return False
        return (now or datetime.now(UTC)) - seen <= timedelta(seconds=STALE_THRESHOLD)

    def stale_candidates(self, now: datetime | None = None) -> list[PeerRecord]:
        """Entries whose heartbeat is older than the stale threshold."""
        now = now or datetime.now(UTC)
        stale = []
        for record in self.list_peers():
            seen = _parse_iso(record.last_seen)
            if seen is None or (now - seen) > timedelta(seconds=STALE_THRESHOLD):
                stale.append(record)
        return stale

    def prune(self, now: datetime | None = None, handshake_alive: HandshakeCheck | None = None) -> list[PeerRecord]:
        """Remove stale entries only after the authoritative handshake fails.

        ``handshake_alive(pid, instance_id)`` comes from the transport layer
        (P5): the socket handshake is the only authority. With no handshake
        callback, prune removes nothing (fail safe).
        """
        now = now or datetime.now(UTC)
        if handshake_alive is None:
            return []
        removed: list[PeerRecord] = []
        for record in self.stale_candidates(now):
            alive = False
            try:
                alive = handshake_alive(record.pid, record.instance_id)
            except Exception:  # noqa: BLE001
                alive = False
            if not alive and self.unregister(record.peer_id):
                removed.append(record)
        return removed

    # -- internals ---------------------------------------------------------

    def _atomic_write(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
