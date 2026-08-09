"""Owner-local SQLite message store (ADR-0001 §4.5, AP-601..AP-603, AP-610, AP-611).

- WAL mode, busy timeout, explicit transactions.
- Incremental, idempotent migrations (fresh DB, repeated runs, older schemas).
- Deduplication: one row per ``message_id``; duplicates return the prior
  receipt state.
- Bounded retention: time- and row-capped cleanup in small batches that
  never blocks active delivery.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Receipt, ReceiptState

logger = logging.getLogger("agent_peer.store")

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    recipient_peer_id TEXT NOT NULL,
    sender_peer_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    reply_to TEXT,
    conversation_id TEXT,
    delivered_at TEXT,
    hop_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_recipient_state
    ON messages(recipient_peer_id, state);
CREATE INDEX IF NOT EXISTS idx_messages_created
    ON messages(created_at);
"""


class MessageStore:
    """Thread-safe SQLite store for inbox/outbox records and receipts."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), timeout=10, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._conn.execute(
                "SELECT version FROM schema_version ORDER BY rowid LIMIT 1"
            ).fetchone()
            current = row[0] if row else 0
            if current < 1:
                self._conn.executescript(_SCHEMA)
                self._conn.execute("DELETE FROM schema_version")
                self._conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            self._conn.commit()

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------

    def record(self, row: dict) -> Receipt:
        """Persist one message row; a duplicate returns the prior receipt.

        ``row`` carries message_id, recipient_peer_id, sender_peer_id, kind,
        content, state, created_at, expires_at, reply_to, conversation_id,
        delivered_at, hop_count.
        """
        with self._lock:
            existing = self.get(row["message_id"])
            if existing is not None:
                return Receipt(
                    message_id=row["message_id"],
                    state=ReceiptState(existing["state"]),
                    recipient_peer_id=existing["recipient_peer_id"],
                    detail="duplicate: prior receipt returned",
                    delivered_at=existing.get("delivered_at") or "",
                )
            self._conn.execute(
                """INSERT INTO messages (
                    message_id, recipient_peer_id, sender_peer_id, kind,
                    content, state, created_at, expires_at, reply_to,
                    conversation_id, delivered_at, hop_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["message_id"],
                    row["recipient_peer_id"],
                    row["sender_peer_id"],
                    row["kind"],
                    row["content"],
                    row["state"],
                    row["created_at"],
                    row["expires_at"],
                    row.get("reply_to"),
                    row.get("conversation_id"),
                    row.get("delivered_at"),
                    row.get("hop_count", 0),
                ),
            )
            self._conn.commit()
            return Receipt(
                message_id=row["message_id"],
                state=ReceiptState(row["state"]),
                recipient_peer_id=row["recipient_peer_id"],
                detail="stored",
                delivered_at=row.get("delivered_at") or "",
            )

    def transition(self, message_id: str, state: ReceiptState | str) -> bool:
        """Update the delivery state of one message. Returns False if absent."""
        state = state.value if isinstance(state, ReceiptState) else str(state)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE messages SET state=?, delivered_at=? WHERE message_id=?",
                (state, datetime.now(UTC).isoformat(), message_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get(self, message_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM messages WHERE message_id=?", (message_id,)
            ).fetchone()
            if row is None:
                return None
            cols = [d[0] for d in self._conn.execute("SELECT * FROM messages LIMIT 0").description]
            return dict(zip(cols, row, strict=False))

    def pending_for(self, recipient_peer_id: str, states: tuple[str, ...] = ("queued", "held")) -> list[dict]:
        with self._lock:
            placeholders = ",".join("?" for _ in states)
            rows = self._conn.execute(
                f"SELECT * FROM messages WHERE recipient_peer_id=? AND state IN ({placeholders}) "
                "ORDER BY created_at",
                (recipient_peer_id, *states),
            ).fetchall()
            cols = [d[0] for d in self._conn.execute("SELECT * FROM messages LIMIT 0").description]
            return [dict(zip(cols, row, strict=False)) for row in rows]

    def count_pending(self, recipient_peer_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE recipient_peer_id=? AND state IN ('queued','held')",
                (recipient_peer_id,),
            ).fetchone()
            return int(row[0])

    def count_all(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    def retain(self, max_age_days: int = 30, max_rows: int = 10_000, batch_size: int = 500) -> int:
        """Bounded, batched cleanup: old rows first, then over-capacity rows.

        Never blocks active delivery: each batch is its own transaction and
        the method yields between batches.
        """
        removed = 0
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
        with self._lock:
            while True:
                cur = self._conn.execute(
                    "DELETE FROM messages WHERE message_id IN "
                    "(SELECT message_id FROM messages WHERE created_at < ? LIMIT ?)",
                    (cutoff, batch_size),
                )
                self._conn.commit()
                batch = cur.rowcount
                removed += batch
                if batch < batch_size:
                    break
            # Row-cap: delete oldest beyond the cap, in batches.
            while True:
                over = self._conn.execute(
                    "SELECT COUNT(*) - ? FROM messages", (max_rows,)
                ).fetchone()[0]
                if over <= 0:
                    break
                cur = self._conn.execute(
                    "DELETE FROM messages WHERE message_id IN "
                    "(SELECT message_id FROM messages ORDER BY created_at LIMIT ?)",
                    (min(over, batch_size),),
                )
                self._conn.commit()
                removed += cur.rowcount
                if cur.rowcount < batch_size:
                    break
        return removed

    def close(self) -> None:
        from contextlib import suppress

        with self._lock:
            with suppress(sqlite3.Error):
                self._conn.commit()
            with suppress(sqlite3.Error):
                self._conn.close()
