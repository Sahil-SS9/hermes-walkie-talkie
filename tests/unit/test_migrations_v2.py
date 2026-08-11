"""Store migration tests (P3.6): idempotent v1->v2, old rows readable as V1."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from agent_peer.store import MessageStore

V1_SCHEMA = """
CREATE TABLE messages (
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
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version (version) VALUES (1);
"""


def _tmp_store() -> tuple[MessageStore, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="store-mig-"))
    return MessageStore(tmp / "messages.sqlite3"), tmp


def _tmp_v1_db() -> tuple[Path, Path]:
    """A fresh directory containing ONLY a V1-schema database."""
    tmp = Path(tempfile.mkdtemp(prefix="store-mig-v1-"))
    db = tmp / "messages.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(V1_SCHEMA)
    conn.commit()
    conn.close()
    return tmp, db


def _v1_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(V1_SCHEMA)
    conn.commit()
    conn.close()


def _version(store: MessageStore) -> int:
    return int(store._conn.execute("SELECT version FROM schema_version").fetchone()[0])


def _has_protocol_col(store: MessageStore) -> bool:
    cols = [d[1] for d in store._conn.execute("PRAGMA table_info(messages)")]
    return "protocol" in cols


def test_fresh_db_is_latest_version():
    store, _ = _tmp_store()
    try:
        assert _version(store) == 4  # schema at v4 after P5 request tables
        assert _has_protocol_col(store)
    finally:
        store.close()


def test_v1_db_upgrades_to_latest_old_rows_readable():
    _, db = _tmp_v1_db()
    store = MessageStore(db)
    try:
        assert _version(store) == 4  # v1 -> latest via incremental migrations
        assert _has_protocol_col(store)
        # A V1-style row (no protocol key) defaults to agent-peer/1, so old
        # records remain readable as V1 (P3.6).
        store.record(
            {
                "message_id": "11111111-1111-4111-8111-111111111111",
                "recipient_peer_id": "22222222-2222-4222-8222-222222222222",
                "sender_peer_id": "33333333-3333-4333-8333-333333333333",
                "kind": "message",
                "content": "legacy",
                "state": "queued",
                "created_at": "2026-08-01T00:00:00+00:00",
                "expires_at": "2026-08-02T00:00:00+00:00",
            }
        )
        row = store.get("11111111-1111-4111-8111-111111111111")
        assert row is not None
        assert row["protocol"] == "agent-peer/1"
    finally:
        store.close()


def test_migration_is_idempotent():
    _, db = _tmp_v1_db()
    s1 = MessageStore(db)
    s1.close()
    # Second reopen must NOT attempt the ALTER again (no duplicate column).
    s2 = MessageStore(db)
    try:
        assert _version(s2) == 4
        assert _has_protocol_col(s2)
    finally:
        s2.close()


def test_v2_row_roundtrips_protocol():
    store, _ = _tmp_store()
    try:
        store.record(
            {
                "message_id": "44444444-4444-4444-8444-444444444444",
                "recipient_peer_id": "22222222-2222-4222-8222-222222222222",
                "sender_peer_id": "33333333-3333-4333-8333-333333333333",
                "kind": "message",
                "content": "v2",
                "state": "queued",
                "created_at": "2026-08-01T00:00:00+00:00",
                "expires_at": "2026-08-02T00:00:00+00:00",
                "protocol": "agent-peer/2",
            }
        )
        row = store.get("44444444-4444-4444-8444-444444444444")
        assert row is not None
        assert row["protocol"] == "agent-peer/2"
    finally:
        store.close()
