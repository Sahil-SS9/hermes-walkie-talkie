"""Structured request/reply workflow store + manager (P5, G4, ADR-0004).

- Requests are durable: state transitions, idempotency key, correlation,
  parent (group) aggregation and an ordered event log (G4.2).
- The immediate transport receipt is distinct from workflow state (G4.4).
- Repeated idempotency key from the same sender returns the original request
  and never creates duplicate work (G4.7).
- Requests are conversational input only; they cannot invoke slash commands,
  answer confirmations, approve tools or bypass policy (G4.9). Cancellation
  is advisory and never interrupts an active protected tool (G4.6, P5.10).
- Deadlines are enforced; expired requests are bounded-cleanup (G4.10, P5.8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .request_models import Request, new_request_id
from .workflows import InvalidTransition, RequestState, is_terminal, transition


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class RequestEvent:
    request_id: str
    state: str
    detail: str
    occurred_at: str


class RequestStore:
    """SQLite-backed request persistence (P5.2)."""

    def __init__(self, store) -> None:
        self._store = store
        self._conn = store._conn

    # -- create ---------------------------------------------------------

    def create(
        self,
        *,
        sender_agent_id: str,
        recipient_agent_id: str,
        summary: str,
        deadline: str,
        idempotency_key: str = "",
        correlation_id: str = "",
        parent_request_id: str = "",
        payload: dict | None = None,
        now: str | None = None,
    ) -> Request:
        """Create (or return the existing request for an idempotent retry).

        The (sender_agent_id, idempotency_key) UNIQUE constraint is the
        cross-process authority: a repeated key returns the original request
        with its current state — never a duplicate row (G4.7).
        """
        ts = now or _now_iso()
        request_id = new_request_id()
        payload_json = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        with self._store._lock:
            if idempotency_key:
                existing = self._conn.execute(
                    "SELECT * FROM requests WHERE sender_agent_id=? AND idempotency_key=?",
                    (sender_agent_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    return self._row_to_request(existing)
            self._conn.execute(
                "INSERT INTO requests (request_id, sender_agent_id, recipient_agent_id, state, summary, "
                "created_at, deadline, idempotency_key, correlation_id, parent_request_id, payload) "
                "VALUES (?, ?, ?, 'created', ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    sender_agent_id,
                    recipient_agent_id,
                    summary,
                    ts,
                    deadline,
                    # NULL (not '') so the UNIQUE(sender,key) constraint only
                    # fires for real idempotency keys; SQLite treats NULLs as
                    # distinct, allowing unlimited keyless requests.
                    idempotency_key or None,
                    correlation_id,
                    parent_request_id,
                    payload_json,
                ),
            )
            self._append_event(request_id, "created", "request created")
            self._conn.commit()
        return Request(
            request_id=request_id,
            sender_agent_id=sender_agent_id,
            recipient_agent_id=recipient_agent_id,
            state=RequestState.CREATED.value,
            summary=summary,
            created_at=ts,
            deadline=deadline,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            parent_request_id=parent_request_id,
            payload=payload or {},
        )

    # -- reads ----------------------------------------------------------

    def get(self, request_id: str) -> Request | None:
        with self._store._lock:
            row = self._conn.execute(
                "SELECT * FROM requests WHERE request_id=?", (request_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_request(row)

    def list_for_recipient(self, recipient_agent_id: str, *, states: tuple[str, ...] | None = None) -> list[Request]:
        with self._store._lock:
            if states:
                placeholders = ",".join("?" for _ in states)
                rows = self._conn.execute(
                    f"SELECT * FROM requests WHERE recipient_agent_id=? AND state IN ({placeholders}) "
                    "ORDER BY created_at",
                    (recipient_agent_id, *states),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM requests WHERE recipient_agent_id=? ORDER BY created_at",
                    (recipient_agent_id,),
                ).fetchall()
        return [self._row_to_request(r) for r in rows]

    def events(self, request_id: str) -> list[RequestEvent]:
        with self._store._lock:
            rows = self._conn.execute(
                "SELECT request_id, state, detail, occurred_at FROM request_events "
                "WHERE request_id=? ORDER BY event_id",
                (request_id,),
            ).fetchall()
        return [RequestEvent(*r) for r in rows]

    # -- transitions ----------------------------------------------------

    def transition(self, request_id: str, target: str, *, detail: str = "") -> Request | None:
        """Apply a legal state transition with an ordered event. Returns the
        updated request or None when the request is absent/terminal-stale."""
        with self._store._lock:
            row = self._conn.execute(
                "SELECT * FROM requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                return None
            data = self._row_dict(row)
            current = RequestState(data["state"])
            if is_terminal(current):
                # A stale writer cannot mutate a terminal request.
                return self._row_to_request(row)
            try:
                target_state = transition(current, target)
            except (InvalidTransition, ValueError):
                return self._row_to_request(row)  # no-op on impossible transition
            self._conn.execute(
                "UPDATE requests SET state=? WHERE request_id=?", (target_state.value, request_id)
            )
            self._append_event(request_id, target_state.value, detail)
            self._conn.commit()
        return self.get(request_id)

    def expire_overdue(self, now: str | None = None) -> int:
        """Bounded expiry: created/queued/in_progress requests past deadline
        become expired (P5.8). Returns the number expired."""
        ref = now or _now_iso()
        count = 0
        with self._store._lock:
            rows = self._conn.execute(
                "SELECT request_id FROM requests WHERE state IN ('created','queued','in_progress') "
                "AND deadline < ?",
                (ref,),
            ).fetchall()
            for (rid,) in rows:
                self._conn.execute(
                    "UPDATE requests SET state='expired' WHERE request_id=?", (rid,)
                )
                self._append_event(rid, "expired", "deadline passed")
                count += 1
            if count:
                self._conn.commit()
        return count

    def count_active(self) -> int:
        with self._store._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM requests WHERE state IN ('created','queued','accepted','in_progress')"
            ).fetchone()
        return int(row[0])

    # -- internals ------------------------------------------------------

    def _append_event(self, request_id: str, state: str, detail: str = "") -> None:
        self._conn.execute(
            "INSERT INTO request_events (request_id, state, detail, occurred_at) VALUES (?, ?, ?, ?)",
            (request_id, state, detail, _now_iso()),
        )

    def _row_dict(self, row) -> dict:
        cols = [d[0] for d in self._conn.execute("SELECT * FROM requests LIMIT 0").description]
        return dict(zip(cols, row, strict=False))

    def _row_to_request(self, row) -> Request:
        data = self._row_dict(row)
        try:
            payload = json.loads(data["payload"]) if data["payload"] else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        return Request(
            request_id=data["request_id"],
            sender_agent_id=data["sender_agent_id"],
            recipient_agent_id=data["recipient_agent_id"],
            state=data["state"],
            summary=data["summary"],
            created_at=data["created_at"],
            deadline=data["deadline"],
            idempotency_key=data["idempotency_key"] or "",
            correlation_id=data["correlation_id"] or "",
            parent_request_id=data["parent_request_id"] or "",
            payload=payload,
        )


__all__ = ["RequestEvent", "RequestStore"]
