"""RED tests for the owner-local SQLite store (AP-601, AP-602, AP-603, AP-610, AP-611)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_peer.models import Kind, ReceiptState
from agent_peer.store import MessageStore

NOW = datetime.now(UTC)


def _msg(recipient: str | None = None, sender: str | None = None, mid: str | None = None, **kw) -> dict:
    return {
        "message_id": mid or str(uuid.uuid4()),
        "recipient_peer_id": recipient or str(uuid.uuid4()),
        "sender_peer_id": sender or str(uuid.uuid4()),
        "kind": kw.pop("kind", Kind.MESSAGE.value),
        "content": kw.pop("content", "hello"),
        "state": kw.pop("state", "queued"),
        "created_at": kw.pop("created_at", NOW.isoformat()),
        "expires_at": kw.pop("expires_at", (NOW + timedelta(minutes=5)).isoformat()),
        "reply_to": kw.pop("reply_to", None),
        "conversation_id": kw.pop("conversation_id", None),
        "delivered_at": kw.pop("delivered_at", None),
        "hop_count": kw.pop("hop_count", 0),
    }


@pytest.fixture
def store_path(tmp_path) -> Path:
    return tmp_path / "messages.sqlite3"


class TestMigrations:
    def test_fresh_db_migrates(self, store_path):
        store = MessageStore(store_path)
        store.close()
        conn = sqlite3.connect(store_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "messages" in tables
        assert "schema_version" in tables
        conn.close()

    def test_repeated_migration_idempotent(self, store_path):
        MessageStore(store_path).close()
        MessageStore(store_path).close()
        MessageStore(store_path).close()  # must not raise
        conn = sqlite3.connect(store_path)
        version = conn.execute("SELECT version FROM schema_version").fetchone()
        assert version is not None
        conn.close()

    def test_older_schema_upgraded(self, store_path):
        # Simulate an older schema: create the DB with version 0 and no
        # messages table, then let the store migrate it.
        conn = sqlite3.connect(store_path)
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        conn.commit()
        conn.close()
        store = MessageStore(store_path)
        store.close()
        conn = sqlite3.connect(store_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "messages" in tables
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] >= 1
        conn.close()


class TestStoreBasics:
    def test_wal_mode_enabled(self, store_path):
        store = MessageStore(store_path)
        journal = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal == "wal"
        store.close()

    def test_record_and_load_round_trip(self, store_path):
        store = MessageStore(store_path)
        row = _msg()
        store.record(row)
        loaded = store.get(row["message_id"])
        assert loaded is not None
        assert loaded["content"] == "hello"
        assert loaded["state"] == "queued"
        store.close()

    def test_pending_by_recipient(self, store_path):
        store = MessageStore(store_path)
        recipient = str(uuid.uuid4())
        store.record(_msg(recipient=recipient, state="held"))
        store.record(_msg(recipient=recipient, state="queued"))
        store.record(_msg(recipient=str(uuid.uuid4()), state="queued"))
        pending = store.pending_for(recipient)
        assert len(pending) == 2
        store.close()

    def test_committed_records_survive_reopen(self, store_path):
        store = MessageStore(store_path)
        row = _msg()
        store.record(row)
        store.close()
        store2 = MessageStore(store_path)
        assert store2.get(row["message_id"]) is not None
        store2.close()

    def test_uncommitted_transaction_does_not_survive(self, store_path):
        conn = sqlite3.connect(store_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY, recipient_peer_id TEXT NOT NULL)"""
        )
        conn.execute("INSERT INTO messages (message_id, recipient_peer_id) VALUES (?, ?)", ("x", "y"))
        # No commit — connection drops.
        conn.close()
        conn2 = sqlite3.connect(store_path)
        rows = conn2.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn2.close()
        assert rows == 0

    def test_state_transition(self, store_path):
        store = MessageStore(store_path)
        row = _msg()
        store.record(row)
        store.transition(row["message_id"], ReceiptState.HELD)
        loaded = store.get(row["message_id"])
        assert loaded["state"] == "held"
        store.close()


class TestDeduplication:
    def test_same_message_id_stored_once(self, store_path):
        store = MessageStore(store_path)
        row = _msg()
        first = store.record(row)
        second = store.record(row)  # duplicate
        assert first.state.value == "queued"
        assert second.state.value == "queued"  # prior receipt returned
        conn = sqlite3.connect(store_path)
        count = conn.execute("SELECT COUNT(*) FROM messages WHERE message_id=?", (row["message_id"],)).fetchone()[0]
        assert count == 1
        conn.close()
        store.close()

    def test_duplicate_returns_prior_receipt(self, store_path):
        store = MessageStore(store_path)
        row = _msg()
        store.record(row)
        store.transition(row["message_id"], "held")
        again = store.record(row)
        assert again.state.value == "held"  # reflects the prior state
        store.close()


class TestRetention:
    def test_old_rows_removed(self, store_path):
        store = MessageStore(store_path)
        old = _msg(created_at=(NOW - timedelta(days=60)).isoformat())
        fresh = _msg(created_at=NOW.isoformat())
        store.record(old)
        store.record(fresh)
        removed = store.retain(max_age_days=30)
        assert removed >= 1
        assert store.get(fresh["message_id"]) is not None
        assert store.get(old["message_id"]) is None
        store.close()

    def test_row_cap_enforced(self, store_path):
        store = MessageStore(store_path)
        for i in range(12):
            store.record(_msg(mid=str(uuid.uuid4()), created_at=(NOW - timedelta(minutes=i)).isoformat()))
        removed = store.retain(max_rows=5)
        assert removed >= 7
        remaining = store.count_all()
        assert remaining <= 5
        store.close()

    def test_retention_never_blocks_active_delivery(self, store_path):
        store = MessageStore(store_path)
        store.record(_msg())
        # Retention runs in bounded batches on the same connection; a normal
        # record must still succeed right after.
        store.retain(max_age_days=1, batch_size=10)
        store.record(_msg())
        assert store.count_all() == 2
        store.close()
