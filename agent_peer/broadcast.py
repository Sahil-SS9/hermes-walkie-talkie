"""Bounded broadcasts (P4, ADR-0004, G3.5..G3.10).

A broadcast is an orchestrator over ordinary point-to-point sends, NOT a new
multi-recipient transport frame:
1. Parent persisted first (one immutable ``broadcast_id``).
2. Every member resolved independently with deterministic routing.
3. Child rows persisted with deterministic IDs derived from
   ``(broadcast_id, recipient agent_id, resolved peer_id)`` BEFORE fan-out.
4. Bounded concurrent sends; per-member results collected in member order.
5. Retrying the parent is idempotent — never reinjects a child (G3.7).
6. Partial success is explicit; no fake all-or-nothing rollback (G3.6).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .constants import (
    BROADCAST_MAX_RETRIES,
    BROADCAST_TTL_SECONDS,
    DEFAULT_FANOUT_CONCURRENCY,
)
from .errors import ValidationError
from .groups import GroupStore

_CHILD_ID_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # DNS


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def deterministic_child_id(broadcast_id: str, agent_id: str, peer_id: str) -> str:
    """Deterministic child message id (G3.5): stable per recipient+sessin."""
    authority = f"{broadcast_id}|{agent_id}|{peer_id}"
    return str(uuid.uuid5(_CHILD_ID_NS, authority))


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    broadcast_id: str
    summary: dict
    per_member: list[dict]


class BroadcastEngine:
    """Persist-parent-first fan-out over deterministic per-recipient sends."""

    def __init__(
        self,
        store,
        groups: GroupStore,
        *,
        send: Callable | None = None,
        resolve: Callable | None = None,
        concurrency: int = DEFAULT_FANOUT_CONCURRENCY,
        ttl_seconds: float = BROADCAST_TTL_SECONDS,
        max_retries: int = BROADCAST_MAX_RETRIES,
    ) -> None:
        """``send`` delivers one resolved peer envelope; ``resolve`` maps an
        agent_id (+ optional pin) to a live PeerRecord. Both are injected so
        the engine stays harness-neutral and testable without sockets."""
        self._store = store
        self._conn = store._conn
        self._groups = groups
        self._send = send or (lambda *a, **k: {"state": "queued"})
        self._resolve = resolve or (lambda agent_id, pin: None)
        if concurrency < 1:
            raise ValidationError("broadcast concurrency must be >= 1")
        self._concurrency = concurrency
        self._ttl = ttl_seconds
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Parent persistence
    # ------------------------------------------------------------------

    def create_broadcast(self, sender_agent_id: str, group_id: str, content: str) -> str:
        """Persist the parent row; returns the immutable broadcast_id."""
        if not sender_agent_id or not group_id:
            raise ValidationError("broadcast requires sender_agent_id and group_id")
        broadcast_id = str(uuid.uuid4())
        with self._store._lock:
            self._conn.execute(
                "INSERT INTO broadcasts (broadcast_id, sender_agent_id, group_id, content, created_at, status) "
                "VALUES (?, ?, ?, ?, ?, 'created')",
                (broadcast_id, sender_agent_id, group_id, content, _now_iso()),
            )
            self._conn.commit()
        return broadcast_id

    # ------------------------------------------------------------------
    # Fan-out
    # ------------------------------------------------------------------

    def fan_out(
        self,
        broadcast_id: str,
        *,
        sender_agent_id: str | None = None,
    ) -> BroadcastResult:
        """Execute the broadcast: resolve members, persist children, send.

        Idempotent per child: re-running the same broadcast id never injects
        a duplicate child (G3.7). The atomic ``created -> in_flight`` parent
        transition is the single-writer gate: concurrent duplicate
        broadcasters converge — exactly one runs the fan-out, the rest read
        the recorded outcomes (P4.7).
        """
        with self._store._lock:
            parent = self._conn.execute(
                "SELECT broadcast_id, sender_agent_id, group_id, content, status FROM broadcasts "
                "WHERE broadcast_id=?",
                (broadcast_id,),
            ).fetchone()
        if parent is None:
            raise ValidationError(f"unknown broadcast {broadcast_id}")
        parent_id, parent_sender, group_id, content, status = parent
        if sender_agent_id is not None and sender_agent_id != parent_sender:
            raise ValidationError("broadcast sender mismatch")
        if status != "created":
            # Already fanned out (or in flight): return the recorded outcomes.
            return self._results(broadcast_id)

        members = self._groups.members(group_id)
        if not members:
            raise ValidationError("broadcast group has no members")

        # Atomic single-writer gate: exactly one caller flips created ->
        # in_flight. The loser re-reads status and returns recorded outcomes
        # (never a duplicate send).
        with self._store._lock:
            won = self._conn.execute(
                "UPDATE broadcasts SET status='in_flight' "
                "WHERE broadcast_id=? AND status='created'",
                (broadcast_id,),
            )
            self._conn.commit()
        if won.rowcount != 1:
            return self._results(broadcast_id)

        # Resolve + persist children BEFORE any send (G3.5).
        resolved: list[tuple[str, str, str, str, str]] = []  # agent, peer, child, state, detail
        for m in members:
            if m.agent_id == parent_sender:
                # Never send to yourself; record a skipped non-delivery.
                resolved.append((m.agent_id, "", deterministic_child_id(broadcast_id, m.agent_id, ""), "skipped", "sender excluded"))
                continue
            record = self._resolve(m.agent_id, m.peer_id or None)
            if record is None:
                resolved.append((m.agent_id, "", deterministic_child_id(broadcast_id, m.agent_id, ""), "unreachable", "no live session"))
                continue
            peer = record.peer_id
            child = deterministic_child_id(broadcast_id, m.agent_id, peer)
            resolved.append((m.agent_id, peer, child, "queued", ""))

        with self._store._lock:
            for agent, peer, child, state, detail in resolved:
                self._conn.execute(
                    "INSERT OR IGNORE INTO broadcast_children "
                    "(broadcast_id, recipient_agent_id, resolved_peer_id, child_message_id, state, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (broadcast_id, agent, peer, child, state, detail),
                )
            self._conn.commit()

        # Bounded concurrent sends (G3.8): a worker pool capped at
        # concurrency, preserving per-member order in the result.
        results: list[dict] = [None] * len(resolved)  # type: ignore[list-item]
        failures = {"count": 0, "items": []}

        def work(idx: int, agent: str, peer: str, child: str, state: str, detail: str) -> None:
            if state != "queued":
                results[idx] = {"agent_id": agent, "peer_id": peer, "child_message_id": child, "state": state, "detail": detail}
                return
            final_state = "queued"
            final_detail = ""
            for attempt in range(self._max_retries + 1):
                try:
                    receipt = self._send(agent, peer, content, child_message_id=child)
                    final_state = receipt.get("state", "queued")
                    final_detail = receipt.get("detail", "")
                    if final_state not in ("unreachable", "timeout"):
                        break
                except Exception as exc:  # noqa: BLE001 - contained per child
                    final_state = "unreachable"
                    final_detail = f"attempt {attempt + 1}: {exc}"
            with self._store._lock:
                self._conn.execute(
                    "UPDATE broadcast_children SET state=?, detail=? WHERE broadcast_id=? AND recipient_agent_id=? AND resolved_peer_id=?",
                    (final_state, final_detail, broadcast_id, agent, peer),
                )
                self._conn.commit()
            results[idx] = {
                "agent_id": agent,
                "peer_id": peer,
                "child_message_id": child,
                "state": final_state,
                "detail": final_detail,
            }

        sem = threading.Semaphore(self._concurrency)
        threads: list[threading.Thread] = []

        def run(idx: int, *args) -> None:
            with sem:
                work(idx, *args)

        for idx, (agent, peer, child, state, detail) in enumerate(resolved):
            t = threading.Thread(target=run, args=(idx, agent, peer, child, state, detail), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        with self._store._lock:
            self._conn.execute(
                "UPDATE broadcasts SET status='completed' WHERE broadcast_id=?",
                (broadcast_id,),
            )
            self._conn.commit()

        failures["count"] = sum(1 for r in results if r["state"] not in ("queued", "held", "accepted", "in_progress", "completed"))
        failures["items"] = [r for r in results if r["state"] not in ("queued", "held", "accepted", "in_progress", "completed")]
        summary = {
            "broadcast_id": broadcast_id,
            "total": len(results),
            "queued": sum(1 for r in results if r["state"] == "queued"),
            "held": sum(1 for r in results if r["state"] == "held"),
            "skipped": sum(1 for r in results if r["state"] == "skipped"),
            "unreachable": sum(1 for r in results if r["state"] == "unreachable"),
            "failures": failures,
        }
        return BroadcastResult(broadcast_id, summary, results)

    def _results(self, broadcast_id: str) -> BroadcastResult:
        """Re-read recorded outcomes for an already-fanned broadcast."""
        with self._store._lock:
            rows = self._conn.execute(
                "SELECT recipient_agent_id, resolved_peer_id, child_message_id, state, detail "
                "FROM broadcast_children WHERE broadcast_id=? ORDER BY recipient_agent_id",
                (broadcast_id,),
            ).fetchall()
        results = [
            {
                "agent_id": r[0],
                "peer_id": r[1],
                "child_message_id": r[2],
                "state": r[3],
                "detail": r[4],
            }
            for r in rows
        ]
        summary = {
            "broadcast_id": broadcast_id,
            "total": len(results),
            "queued": sum(1 for r in results if r["state"] == "queued"),
            "held": sum(1 for r in results if r["state"] == "held"),
            "skipped": sum(1 for r in results if r["state"] == "skipped"),
            "unreachable": sum(1 for r in results if r["state"] == "unreachable"),
            "failures": {"count": sum(1 for r in results if r["state"] == "unreachable"), "items": [r for r in results if r["state"] == "unreachable"]},
        }
        return BroadcastResult(broadcast_id, summary, results)


__all__ = ["BroadcastEngine", "BroadcastResult", "deterministic_child_id"]
