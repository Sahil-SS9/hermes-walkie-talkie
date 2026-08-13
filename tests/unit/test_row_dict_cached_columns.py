"""CAREFUL-3: _row_dict caches request column names once.

The schema introspection query (SELECT * FROM requests LIMIT 0) must not
run once per converted row. Multiple request conversions on one store
should only issue the introspection query a single time, while row
ordering and public objects are preserved.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_peer.requests import RequestStore
from agent_peer.store import MessageStore

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _rs() -> RequestStore:
    return RequestStore(MessageStore(Path(tempfile.mkdtemp()) / "r.sqlite3"))


class TestRowDictCachedColumns:
    def test_columns_introspected_once(self):
        rs = _rs()
        for i in range(5):
            rs.create(
                sender_agent_id=A,
                recipient_agent_id=B,
                summary=f"s{i}",
                deadline="2099-01-01T00:00:00+00:00",
                idempotency_key=f"k{i}",
            )
        rows = rs.list_for_recipient(B)
        assert len(rows) == 5
        # The introspection query is issued exactly once: the lazy cache is
        # set after the first conversion, so later conversions reuse it.
        rs._columns = None  # force lazy init

        class SpyConn:
            """Delegating connection wrapper that counts introspection."""

            def __init__(self, real):
                self._real = real
                self.introspections = 0

            def execute(self, sql, *args, **kwargs):
                if sql == "SELECT * FROM requests LIMIT 0":
                    self.introspections += 1
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        spy = SpyConn(rs._conn)
        rs._conn = spy
        # Convert every row via get() (which runs _row_dict internally).
        for row in rows:
            conv = rs.get(row.request_id)
            assert conv is not None and conv.summary.startswith("s")
        assert spy.introspections == 1, "column introspection ran more than once"

    def test_row_ordering_preserved(self):
        rs = _rs()
        r1 = rs.create(
            sender_agent_id=A,
            recipient_agent_id=B,
            summary="first",
            deadline="2099-01-01T00:00:00+00:00",
            idempotency_key="k10",
        )
        r2 = rs.create(
            sender_agent_id=A,
            recipient_agent_id=B,
            summary="second",
            deadline="2099-01-01T00:00:00+00:00",
            idempotency_key="k11",
        )
        got = rs.list_for_recipient(B)
        assert [g.request_id for g in got] == [r1.request_id, r2.request_id]
        assert got[0].summary == "first"
        assert got[1].summary == "second"
