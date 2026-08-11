"""Persistent groups (P4, ADR-0004, G3).

Groups store immutable ``agent_id`` membership (never mutable alias/path as
authority, G3.3); an optional exact ``peer_id`` pin is allowed for a
session-specific member (G3.2). No nested groups in this release (G3.4).
Optimistic revision protects concurrent updates (G3.1).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from .constants import DEFAULT_GROUP_CAP, HARD_GROUP_CAP
from .errors import ValidationError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,62}[A-Za-z0-9]$|^[A-Za-z0-9]$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalise_group_name(name: str) -> str:
    """Normalise a group name: strip, case-fold, length-check, charset."""
    if not isinstance(name, str):
        raise ValidationError("group name must be a string")
    norm = name.strip().casefold()
    if not norm:
        raise ValidationError("group name must not be empty")
    if len(norm) > 64:
        raise ValidationError("group name exceeds 64 characters")
    if not _NAME_RE.match(norm):
        raise ValidationError(
            "group name may only contain letters, digits, dot, dash, underscore"
        )
    return norm


@dataclass(frozen=True, slots=True)
class Group:
    group_id: str
    name: str
    owner_agent_id: str
    created_at: str
    updated_at: str
    revision: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id:
            raise ValidationError("group_id must be a non-empty string")
        if not isinstance(self.owner_agent_id, str) or not self.owner_agent_id:
            raise ValidationError("owner_agent_id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class GroupMember:
    group_id: str
    agent_id: str
    peer_id: str = ""


class GroupStore:
    """SQLite-backed group CRUD with optimistic revision (P4.1/P4.2)."""

    def __init__(self, store) -> None:
        # The owning MessageStore provides the connection + lock.
        self._store = store
        self._conn = store._conn

    # -- create ---------------------------------------------------------

    def create_group(
        self,
        owner_agent_id: str,
        name: str,
        *,
        now: str | None = None,
    ) -> Group:
        group_id = str(uuid.uuid4())
        norm = normalise_group_name(name)
        ts = now or _now_iso()
        with self._store._lock:
            try:
                self._conn.execute(
                    "INSERT INTO groups (group_id, name, owner_agent_id, created_at, updated_at, revision) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (group_id, norm, owner_agent_id, ts, ts),
                )
                self._conn.commit()
            except Exception as exc:
                if "UNIQUE" in str(exc):
                    raise ValidationError(
                        f"group name {norm!r} already exists (names are unique)"
                    ) from exc
                raise
        return Group(group_id, norm, owner_agent_id, ts, ts, 0)

    # -- reads ----------------------------------------------------------

    def get_group(self, group_id: str) -> Group | None:
        with self._store._lock:
            row = self._conn.execute(
                "SELECT group_id, name, owner_agent_id, created_at, updated_at, revision "
                "FROM groups WHERE group_id=?",
                (group_id,),
            ).fetchone()
        if row is None:
            return None
        return Group(*row)

    def get_group_by_name(self, name: str) -> Group | None:
        norm = normalise_group_name(name)
        with self._store._lock:
            row = self._conn.execute(
                "SELECT group_id, name, owner_agent_id, created_at, updated_at, revision "
                "FROM groups WHERE name=?",
                (norm,),
            ).fetchone()
        if row is None:
            return None
        return Group(*row)

    def list_groups(self) -> list[Group]:
        with self._store._lock:
            rows = self._conn.execute(
                "SELECT group_id, name, owner_agent_id, created_at, updated_at, revision "
                "FROM groups ORDER BY name"
            ).fetchall()
        return [Group(*r) for r in rows]

    # -- mutation -------------------------------------------------------

    def rename_group(self, group_id: str, new_name: str, *, expected_revision: int) -> Group | None:
        """Rename iff the optimistic revision still matches; else None."""
        norm = normalise_group_name(new_name)
        with self._store._lock:
            cur = self._conn.execute(
                "UPDATE groups SET name=?, updated_at=?, revision=revision+1 "
                "WHERE group_id=? AND revision=?",
                (norm, _now_iso(), group_id, expected_revision),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                return None
        return self.get_group(group_id)

    def delete_group(self, group_id: str, *, owner_agent_id: str | None = None) -> bool:
        """Delete a group; optional owner fence (P4.3)."""
        with self._store._lock:
            if owner_agent_id is not None:
                cur = self._conn.execute(
                    "DELETE FROM groups WHERE group_id=? AND owner_agent_id=?",
                    (group_id, owner_agent_id),
                )
            else:
                cur = self._conn.execute("DELETE FROM groups WHERE group_id=?", (group_id,))
            self._conn.commit()
            return cur.rowcount == 1

    # -- membership -----------------------------------------------------

    def add_member(self, group_id: str, agent_id: str, *, peer_id: str = "") -> bool:
        """Add one member (stable agent_id; optional exact peer pin, G3.2).

        Returns False when the group does not exist or the member is already
        present (idempotent add).
        """
        if not agent_id:
            raise ValidationError("member agent_id must be non-empty")
        with self._store._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM groups WHERE group_id=?", (group_id,)
            ).fetchone()
            if exists is None:
                return False
            self._conn.execute(
                "INSERT OR IGNORE INTO group_members (group_id, agent_id, peer_id) VALUES (?, ?, ?)",
                (group_id, agent_id, peer_id or None),
            )
            self._conn.commit()
            return True

    def remove_member(self, group_id: str, agent_id: str) -> bool:
        with self._store._lock:
            cur = self._conn.execute(
                "DELETE FROM group_members WHERE group_id=? AND agent_id=?",
                (group_id, agent_id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def members(self, group_id: str) -> list[GroupMember]:
        with self._store._lock:
            rows = self._conn.execute(
                "SELECT group_id, agent_id, COALESCE(peer_id, '') FROM group_members "
                "WHERE group_id=? ORDER BY agent_id",
                (group_id,),
            ).fetchall()
        return [GroupMember(*r) for r in rows]

    def member_count(self, group_id: str) -> int:
        with self._store._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM group_members WHERE group_id=?", (group_id,)
            ).fetchone()
        return int(row[0])

    def validate_cap(self, member_count: int, *, cap: int = DEFAULT_GROUP_CAP) -> None:
        """Enforce the configurable cap within the hard ceiling (G3.8/G3.9)."""
        if cap < 1 or cap > HARD_GROUP_CAP:
            raise ValidationError(f"group cap {cap} outside 1..{HARD_GROUP_CAP}")
        if member_count + 1 > cap:
            raise ValidationError(
                f"group member cap {cap} exceeded (hard ceiling {HARD_GROUP_CAP})"
            )


__all__ = ["Group", "GroupMember", "GroupStore", "normalise_group_name"]
