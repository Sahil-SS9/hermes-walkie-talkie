"""Hermes session lifecycle -> peer registrations (HP-703, HP-704, HP-705, HP-708, HP-709).

The session manager maps host lifecycle events to the process-global
:class:`~agent_peer.runtime.PeerRuntimeManager`:

- ``on_session_start`` registers a peer (status ``working``).
- ``on_session_end`` marks it ``idle``.
- ``on_session_reset`` re-registers under the NEW session id (alias and
  inbox state survive; the stale host target is never reused).
- ``on_session_finalize`` removes the registration and its socket.

Host targets are captured as plain arguments (context-bound), never from
inherited thread context (HP-704). One TUI/gateway process may register
several exact peers through the same supervisor (HP-708).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC
from pathlib import Path

from agent_peer.discovery import DiscoveryService
from agent_peer.identity import AliasStore, generate_instance_id, generate_peer_id, host_metadata
from agent_peer.models import (
    Envelope,
    Kind,
    PeerIdentity,
    PeerRecord,
    Policy,
    Presence,
    ReceiptState,
)
from agent_peer.paths import RuntimePaths, select_runtime_dir, select_state_dir
from agent_peer.policy import PolicyEngine
from agent_peer.registry import Registry
from agent_peer.runtime import PeerHandle, PeerRuntimeManager
from agent_peer.store import MessageStore

from .config import PeerConfig

logger = logging.getLogger("hermes_peer.sessions")


def _surface_of(platform: str | None) -> str:
    if not platform or platform in ("", "cli"):
        return "cli"
    if platform in ("tui", "webui", "desktop", "dashboard"):
        return "tui"
    return "gateway"


def _hermes_home(ctx) -> Path | None:
    """Resolve the live profile's HERMES_HOME (G2.3).

    Preference: the plugin context's ``hermes_home`` when present, then the
    ``HERMES_HOME`` env var. Returns ``None`` when neither is known — the
    caller must NOT guess ``~/.hermes`` (tests would mutate the real profile).
    """
    for candidate in (
        getattr(ctx, "hermes_home", None),
        os.environ.get("HERMES_HOME"),
    ):
        if candidate:
            return Path(candidate)
    return None


def host_target_for(surface: str, session_id: str) -> str:
    """Opaque Hermes-owned routing token (ADR-0002)."""
    return f"{surface}:{session_id}"


class PeerSessionManager:
    """Maps Hermes session lifecycle events to Agent Peer registrations."""

    def __init__(self, ctx, runtime_root: Path | RuntimePaths | None = None, config: PeerConfig | None = None) -> None:
        self._ctx = ctx
        self._config = config or PeerConfig()
        self._paths = runtime_root if isinstance(runtime_root, RuntimePaths) else RuntimePaths(runtime_root or select_runtime_dir())
        self._registry = Registry(self._paths)
        self._aliases = AliasStore(Path(self._paths.root) / "aliases.json")
        state_dir = select_state_dir()
        self._store = MessageStore(state_dir / "messages.sqlite3")
        self._runtime = PeerRuntimeManager(self._paths, registry=self._registry)
        self._discovery = DiscoveryService(self._paths, registry=self._registry)
        self._peers: dict[str, PeerRecord] = {}  # session_id -> record
        self._session_to_peer: dict[str, str] = {}  # session_id -> peer_id
        self._peer_handles: dict[str, PeerHandle] = {}
        self._policy = PolicyEngine(policy=self._config.inbound)
        self._session_policies: dict[str, Policy] = {}  # peer_id -> session-scoped policy
        self._agent_id_cache: str | None = None
        # P6 observability: content-free metrics + bounded local events.
        from agent_peer.events import EventBroker
        from agent_peer.metrics import MetricsRegistry

        self._metrics = MetricsRegistry()
        self._events = EventBroker()

    # ------------------------------------------------------------------
    # V2 stable identity (G2.3, P3.2)
    # ------------------------------------------------------------------

    def _agent_id(self) -> str:
        """The profile's long-lived agent identity (G2.3).

        Persisted owner-only inside the REAL HERMES_HOME when one is known
        (plugin context or ``HERMES_HOME`` env). When no home is resolvable
        (bare test contexts), an ephemeral UUID is used and NEVER written to
        the user's home directory — tests must not mutate the real profile.
        """
        if self._agent_id_cache is None:
            home = _hermes_home(self._ctx)
            if home is None:
                import uuid as _uuid

                self._agent_id_cache = str(_uuid.uuid4())
            else:
                from agent_peer.agent_identity import load_or_create_agent_id

                self._agent_id_cache = load_or_create_agent_id(home)
        return self._agent_id_cache

    # ------------------------------------------------------------------
    # Lifecycle hooks (fired by Hermes with explicit kwargs — never
    # inherited thread context, HP-704).
    # ------------------------------------------------------------------

    def on_session_open(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        """Host-open: register the peer when the live session is addressable,
        BEFORE its first model turn (F-09/REM-304/306/308).

        Registration persists while the session is open; working/idle are
        turn states set by on_session_start/on_session_end.
        """
        alias_override = kwargs.pop("_alias_override", None)
        surface = _surface_of(platform)
        existing = self._session_to_peer.get(session_id)
        if existing is not None:
            return
        meta = host_metadata()
        peer_id = generate_peer_id()
        alias = alias_override or self._aliases.effective_name(
            peer_id, default_base=os.path.basename(os.getcwd()) or "session"
        )
        record = PeerRecord(
            peer_id=peer_id,
            instance_id=generate_instance_id(),
            session_id=session_id,
            name=alias,
            profile=kwargs.get("profile", ""),
            agent_id=self._agent_id(),
            protocols=self._config.protocols,
            capabilities=self._config.capabilities,
            surface=surface,
            host_target=host_target_for(surface, session_id),
            pid=meta["pid"],
            cwd=meta["cwd"],
            git_repo_root=meta["git_repo_root"],
            git_branch=meta["git_branch"],
            started_at=meta["started_at"],
            last_seen=meta["started_at"],
            status=Presence.IDLE.value,
            socket_path="",
        )
        handle = self._runtime.register_peer(record, on_message=self._on_inbound)
        # Store the CANONICAL BOUND record (F-02/REM-203): register_peer
        # publishes a record with socket_path/socket_uid/socket_inode filled
        # in; every map must hold that exact bound record, never the pre-bind
        # blank copy.
        bound = handle.record or record
        self._peers[session_id] = bound
        self._session_to_peer[session_id] = bound.peer_id
        self._peer_handles[bound.peer_id] = handle
        if alias_override:
            self._aliases.set_alias(bound.peer_id, alias_override)
        logger.info("hermes-peer: opened peer %s (%s) on %s", bound.name, bound.peer_id, surface)

    def on_session_start(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        """Turn-start: the exact session's peer becomes working.

        Registration is owned by on_session_open; this hook only maps the
        turn lifecycle to presence (F-09/REM-308). A legacy host that fires
        on_session_start without on_session_open still registers on first
        start (backwards compatible).
        """
        existing = self._session_to_peer.get(session_id)
        if existing is not None:
            self._set_presence(session_id, Presence.WORKING)
            return
        # Legacy host: no on_session_open fired — register here (idle then
        # immediately working) to preserve the old contract.
        self.on_session_open(session_id, platform=platform, **kwargs)
        if self._session_to_peer.get(session_id) is not None:
            self._set_presence(session_id, Presence.WORKING)

    def _set_presence(self, session_id: str, status: Presence) -> None:
        """Fence and synchronise registry/runtime/session metadata."""
        rec = self._peers.get(session_id)
        if rec is None:
            return
        updated = self._registry.update_presence(rec.peer_id, status, expected=rec)
        if updated is None:
            return
        self._runtime.update_record(updated)
        self._peers[session_id] = updated

    def on_session_end(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        if self._session_to_peer.get(session_id) is not None:
            self._set_presence(session_id, Presence.IDLE)

    def on_session_reset(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        """Session rotation: close the EXACT old registration, register the new id.

        The hook carries the NEW session id plus ``old_session_id`` (when the
        host seam threads it, REM-307). Only that exact old session is
        finalised; unrelated sessions in the same process are never touched
        (F-03/REM-208). The alias and inbox state survive; the stale host
        target is never reused (HP-709).
        """
        old_session = kwargs.get("old_session_id")
        if old_session is None:
            # Backwards-compatible single-session path: a CLI process owns one
            # peer, so rotate it. In a multi-session process without the old
            # id, never silently close every session.
            if len(self._session_to_peer) == 1:
                old_session = next(iter(self._session_to_peer))
            else:
                raise ValueError(
                    "on_session_reset requires old_session_id when multiple sessions are active"
                )
        self._rotate_session(old_session, session_id, platform=platform, **kwargs)

    def _rotate_session(self, old_session: str, new_session: str, platform: str | None = None, **kwargs) -> None:
        """Finalise exactly one old session and register the new one."""
        explicit_alias: str | None = None
        peer_id = self._session_to_peer.pop(old_session, None)
        if peer_id is not None:
            handle = self._peer_handles.pop(peer_id, None)
            if handle is not None:
                handle.close()
            old_record = self._peers.pop(old_session, None)
            self._session_policies.pop(peer_id, None)
            if old_record is not None and old_record.name:
                explicit_alias = self._aliases.get_alias(old_record.peer_id)
        self.on_session_start(
            new_session,
            platform=platform,
            _alias_override=explicit_alias,
            **kwargs,
        )

    def on_session_finalize(self, session_id: str, platform: str | None = None, reason: str = "shutdown", **kwargs) -> None:
        peer_id = self._session_to_peer.pop(session_id, None)
        if peer_id is None:
            return
        handle = self._peer_handles.pop(peer_id, None)
        if handle is not None:
            handle.close()
        self._peers.pop(session_id, None)
        self._session_policies.pop(peer_id, None)
        logger.info("hermes-peer: removed peer for session %s (%s)", session_id, reason)

    def shutdown(self) -> None:
        for session_id in list(self._session_to_peer.keys()):
            self.on_session_finalize(session_id, reason="plugin_shutdown")
        self._runtime.shutdown()
        self._store.close()

    # ------------------------------------------------------------------
    # Public surface used by tools/commands (P8)
    # ------------------------------------------------------------------

    def list_peers(self, *, include_self: bool = True) -> list[PeerRecord]:
        """Return LIVE peers via the discovery service (F-01).

        Cross-process records are discovered and probed; the local handle
        map is never used as a filter. ``include_self=False`` excludes this
        process's own peers (used by listing surfaces).
        """
        requesting = frozenset(self._peer_handles) if not include_self else None
        return list(self._discovery.list_live_peers(requesting_peer_ids=requesting))

    def resolve_target(self, target: str) -> tuple[PeerRecord | None, dict | None]:
        """Fail-closed target resolution via the discovery service (REM-110)."""
        return self._discovery.resolve_peer(target)

    def resolve_peer(self, peer_id: str) -> PeerRecord | None:
        return self._registry.get(peer_id)

    def _require_session(self, session_id: str) -> PeerRecord:
        """Return the exact session's bound record or raise (F-03).

        Multi-session hosts must never fall back to first-peer selection.
        """
        rec = self._peers.get(session_id)
        if rec is None:
            raise ValueError(f"no active peer for session {session_id!r}")
        return rec

    def set_alias(self, name: str, session_id: str | None = None) -> None:
        """Persist an alias for the exact invoking session (F-03/REM-205)."""
        # Backwards-compatible single-session fallback: when exactly one
        # session is registered and none is named, use it (documented).
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        renamed = self._registry.update_if_current(
            rec.peer_id,
            expected_instance_id=rec.instance_id,
            expected_socket_path=rec.socket_path,
            expected_socket_uid=rec.socket_uid,
            expected_socket_inode=rec.socket_inode,
            name=name,
        )
        if renamed is None:
            raise RuntimeError("peer authority changed during alias update")
        self._aliases.set_alias(rec.peer_id, name)
        self._runtime.update_record(renamed)
        self._peers[session_id] = renamed

    def peer_id_for_session(self, session_id: str) -> str | None:
        return self._session_to_peer.get(session_id)

    def _make_envelope(self, *, recipient: str, content: str, reply_to: str | None = None, kind: Kind = Kind.MESSAGE, conversation_id: str | None = None, session_id: str | None = None) -> Envelope:
        """Build a validated outbound envelope from the EXACT session (F-03).

        ``session_id`` must identify the invoking session. Multi-session
        hosts never fall back to first-peer selection.
        """
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        sender_rec = self._require_session(session_id)
        sender = PeerIdentity(peer_id=sender_rec.peer_id, name=sender_rec.name, profile=sender_rec.profile)
        from agent_peer.models import make_envelope

        return make_envelope(
            sender=sender,
            recipient_peer_id=recipient,
            kind=kind,
            content=content,
            reply_to=reply_to,
            conversation_id=conversation_id,
        )

    def _policy_engine_for(self, peer_id: str) -> PolicyEngine:
        """A policy engine for the exact recipient peer (REM-210).

        Session-scoped policy overrides the process-global default for that
        peer. The rate/capacity limiter is shared per engine instance, so
        session-scoped engines carry their own limiter.
        """
        session_policy = self._session_policies.get(peer_id)
        if session_policy is not None:
            return PolicyEngine(policy=session_policy)
        return self._policy

    def _on_inbound(self, envelope: Envelope) -> ReceiptState:
        """Policy-driven inbound pipeline: evaluate, persist, forward/hold/refuse.

        - accept -> forward to the harness via the public inject seam
          (queued only after host acceptance).
        - hold -> persist without forwarding; explicit release/refuse actions
          come from the tools/commands (HP-803).
        - refuse -> persist minimal audit metadata (content never stored).
        - expired/rate_limited/over_capacity/invalid -> audit row only, the
          sender gets the explicit non-success receipt.

        Policy is evaluated against the EXACT recipient session (REM-210).

        Duplicate contract (F-06/REM-401/402): the ``message_id`` is claimed
        atomically under the store lock BEFORE policy evaluation or host
        delivery. If the row already exists, the exact original persisted
        ``ReceiptState`` is returned — policy is NOT re-evaluated, the host
        is NOT re-injected, and prior state is NOT transitioned. Concurrent
        duplicates converge on one row, one injection and one state.
        """
        base_row = {
            "message_id": envelope.message_id,
            "recipient_peer_id": envelope.recipient_peer_id,
            "sender_peer_id": envelope.sender.peer_id,
            "kind": envelope.kind.value,
            "content": envelope.content,
            "created_at": envelope.created_at.isoformat(),
            "expires_at": envelope.expires_at.isoformat(),
            "reply_to": envelope.reply_to,
            "conversation_id": envelope.conversation_id,
            "delivered_at": None,
            "hop_count": envelope.hop_count,
        }
        # Atomic claim: exactly one caller creates the row; every other
        # concurrent caller sees the existing row and returns its state.
        claim_row = {**base_row, "state": ReceiptState.QUEUED.value}
        existing, created = self._store.claim(claim_row)
        if not created and existing is not None:
            state = ReceiptState(existing["state"])
            self._record_inbound_metrics(state, delivered=False)
            return state

        engine = self._policy_engine_for(envelope.recipient_peer_id)
        engine.register_pending(envelope.recipient_peer_id, self._store.count_pending(envelope.recipient_peer_id))
        decision = engine.evaluate(envelope)
        state = decision.state.value

        if decision.action == "drop":
            self._store.transition(envelope.message_id, state)
            self._record_inbound_metrics(decision.state, delivered=False)
            return decision.state

        if decision.action == "refuse":
            # Minimal audit metadata only (AP-606): drop content.
            self._store.transition(envelope.message_id, ReceiptState.REFUSED)
            row = self._store.get(envelope.message_id)
            if row is not None:
                self._store._conn.execute(
                    "UPDATE messages SET content=? WHERE message_id=?",
                    ("", envelope.message_id),
                )
                self._store._conn.commit()
            self._record_inbound_metrics(ReceiptState.REFUSED, delivered=False)
            return ReceiptState.REFUSED

        if decision.action == "hold":
            self._store.transition(envelope.message_id, ReceiptState.HELD)
            self._metrics.record_held(self._store.count_pending(envelope.recipient_peer_id))
            self._record_inbound_metrics(ReceiptState.HELD, delivered=False)
            return ReceiptState.HELD

        # accept: forward to the harness; queued only after host acceptance.
        from .delivery import DeliveryAdapter

        accepted = DeliveryAdapter(self._ctx, self).deliver(envelope, force=True)
        if not accepted:
            self._store.transition(envelope.message_id, ReceiptState.HELD)
            self._metrics.record_held(self._store.count_pending(envelope.recipient_peer_id))
            self._record_inbound_metrics(ReceiptState.HELD, delivered=False)
            return ReceiptState.HELD
        self._record_inbound_metrics(ReceiptState.QUEUED, delivered=True)
        return ReceiptState.QUEUED

    def _record_inbound_metrics(self, state: ReceiptState, *, delivered: bool) -> None:
        """Content-free metrics + bounded local event for one inbound (P6)."""
        self._metrics.record_delivery(sent=delivered, reason="" if delivered else state.value)
        self._events.publish("message", state=state.value, delivered=delivered)

    # ------------------------------------------------------------------
    # Outbound + inbox operations used by tools/commands (P8)
    # ------------------------------------------------------------------

    def send_message(self, peer_id: str, content: str, reply_to: str | None = None, session_id: str | None = None) -> dict:
        """Send one message from the EXACT session (F-03/REM-209)."""
        env = self._make_envelope(recipient=peer_id, content=content, reply_to=reply_to, session_id=session_id)
        receipt = self._runtime.send(env)
        return receipt.as_dict()

    def read_inbox(self, session_id: str | None = None) -> list[dict]:
        """Held and queued messages for the EXACT session (F-03/REM-207)."""
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        return self._store.pending_for(rec.peer_id)

    def release_message(self, message_id: str, session_id: str | None = None) -> bool:
        """Explicit release of a held message owned by the EXACT session."""
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        row = self._store.get(message_id)
        if row is None or row["state"] != ReceiptState.HELD.value:
            return False
        if row["recipient_peer_id"] != rec.peer_id:
            # A message addressed to another session cannot be released here.
            return False
        try:
            env = self._envelope_from_row(row)
        except Exception:  # noqa: BLE001
            return False
        from .delivery import DeliveryAdapter

        return DeliveryAdapter(self._ctx, self).deliver(env, force=True)

    def refuse_message(self, message_id: str, session_id: str | None = None) -> bool:
        """Explicit refuse of a held message owned by the EXACT session."""
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        row = self._store.get(message_id)
        if row is None or row["state"] != ReceiptState.HELD.value:
            return False
        if row["recipient_peer_id"] != rec.peer_id:
            return False
        return self._store.transition(message_id, ReceiptState.REFUSED)

    def set_policy(self, policy_name: str, session_id: str | None = None) -> None:
        """Set the inbound policy for the EXACT session (F-03/REM-210)."""
        from agent_peer.models import Policy

        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        self._session_policies[rec.peer_id] = Policy(policy_name)

    def policy_for(self, session_id: str) -> str:
        """The inbound policy for one exact session (default: global)."""
        rec = self._require_session(session_id)
        policy = self._session_policies.get(rec.peer_id)
        return policy.value if policy is not None else self._policy.policy.value

    def set_alias_for(self, peer_id: str, name: str) -> None:
        """Persist an alias for an exact peer id (used by tools/tests)."""
        record = self._registry.get(peer_id)
        if record is not None:
            renamed = self._registry.update_if_current(
                peer_id,
                expected_instance_id=record.instance_id,
                expected_socket_path=record.socket_path,
                expected_socket_uid=record.socket_uid,
                expected_socket_inode=record.socket_inode,
                name=name,
            )
            if renamed is None:
                return
            self._aliases.set_alias(peer_id, name)
            self._runtime.update_record(renamed)
            for session_id, rec in self._peers.items():
                if rec.peer_id == peer_id:
                    self._peers[session_id] = renamed

    # ------------------------------------------------------------------
    # Structured request/reply workflows (P5, G4)
    # ------------------------------------------------------------------

    def _request_store(self):
        from agent_peer.requests import RequestStore

        if getattr(self, "_requests", None) is None:
            self._requests = RequestStore(self._store)
        return self._requests

    def create_request(
        self,
        recipient_agent_id: str,
        summary: str,
        *,
        payload: dict | None = None,
        deadline: str | None = None,
        idempotency_key: str = "",
        session_id: str | None = None,
    ) -> dict:
        """Create + enqueue a structured request to one agent (G4).

        The request is persisted, transitioned to queued, and delivered to
        the recipient as inert conversational input (``<peer_request>``).
        The immediate transport result is separate from workflow state (G4.4).
        """
        from datetime import datetime, timedelta

        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        sender_rec = self._require_session(session_id)
        sender_agent = sender_rec.agent_id or sender_rec.peer_id
        if not deadline:
            deadline = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        store = self._request_store()
        request = store.create(
            sender_agent_id=sender_agent,
            recipient_agent_id=recipient_agent_id,
            summary=summary,
            deadline=deadline,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        # Enqueue (created -> queued).
        store.transition(request.request_id, "queued")
        # Deliver as inert conversational input to the recipient agent's
        # primary live session. Failure to deliver does NOT roll back the
        # workflow state — the request stays queued for bounded polling.
        from .delivery import peer_request_marker

        recipient = self._discovery.resolve_agent(recipient_agent_id)
        delivered = False
        if recipient is not None:
            wrapped = peer_request_marker(
                request.summary,
                sender_name=sender_rec.name or "peer",
                sender_agent_id=sender_agent,
                request_id=request.request_id,
                summary=request.summary,
            )
            env = self._make_envelope(
                recipient=recipient.peer_id,
                content=wrapped,
                session_id=session_id,
            )
            receipt = self._runtime.send(env)
            delivered = receipt.state in (ReceiptState.QUEUED, ReceiptState.HELD)
        return {
            "request_id": request.request_id,
            "state": request.state,
            "delivered": delivered,
            "recipient_agent_id": recipient_agent_id,
        }

    def request_status(self, request_id: str, *, session_id: str | None = None) -> dict:
        store = self._request_store()
        request = store.get(request_id)
        if request is None:
            raise ValueError(f"unknown request {request_id}")
        events = [
            {"state": e.state, "detail": e.detail, "occurred_at": e.occurred_at}
            for e in store.events(request_id)
        ]
        return {
            "request_id": request.request_id,
            "state": request.state,
            "summary": request.summary,
            "sender_agent_id": request.sender_agent_id,
            "recipient_agent_id": request.recipient_agent_id,
            "created_at": request.created_at,
            "deadline": request.deadline,
            "events": events,
        }

    def request_respond(
        self,
        request_id: str,
        action: str,
        *,
        detail: str = "",
        session_id: str | None = None,
    ) -> dict:
        """Recipient action: accept|progress|complete|fail|refuse (G4.5)."""
        store = self._request_store()
        request = store.get(request_id)
        if request is None:
            raise ValueError(f"unknown request {request_id}")
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        if rec.agent_id != request.recipient_agent_id and rec.peer_id != request.recipient_agent_id:
            raise ValueError("only the recipient may respond to this request")
        target = {
            "accept": "accepted",
            "progress": "in_progress",
            "complete": "completed",
            "fail": "failed",
            "refuse": "refused",
        }.get(action)
        if target is None:
            raise ValueError(f"unknown request action {action!r}")
        updated = store.transition(request.request_id, target, detail=detail)
        return {"request_id": request.request_id, "state": updated.state if updated else request.state}

    def request_cancel(self, request_id: str, *, session_id: str | None = None) -> dict:
        """Advisory cancellation: never interrupts an active tool (G4.6)."""
        store = self._request_store()
        request = store.get(request_id)
        if request is None:
            raise ValueError(f"unknown request {request_id}")
        updated = store.transition(request.request_id, "cancelled", detail="cancelled by sender")
        return {"request_id": request.request_id, "state": updated.state if updated else request.state}

    def request_expire_overdue(self) -> int:
        """Bounded expiry cleanup (P5.8)."""
        return self._request_store().expire_overdue()

    # ------------------------------------------------------------------
    # Groups and broadcasts (P4/P7)
    # ------------------------------------------------------------------

    def _group_store(self):
        from agent_peer.groups import GroupStore

        if getattr(self, "_groups", None) is None:
            self._groups = GroupStore(self._store)
        return self._groups

    def group_create(self, name: str, *, session_id: str | None = None) -> dict:
        """Create a group owned by the invoking session's agent (G3.1)."""
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        owner = rec.agent_id or rec.peer_id
        g = self._group_store().create_group(owner, name)
        return {"group_id": g.group_id, "name": g.name, "owner_agent_id": g.owner_agent_id}

    def group_list(self, *, session_id: str | None = None) -> list[dict]:
        groups = self._group_store().list_groups()
        return [
            {
                "group_id": g.group_id,
                "name": g.name,
                "owner_agent_id": g.owner_agent_id,
                "members": self._group_store().member_count(g.group_id),
            }
            for g in groups
        ]

    def group_add_member(
        self, group_id: str, member_agent_id: str, *, peer_id: str = "", session_id: str | None = None
    ) -> dict:
        ok = self._group_store().add_member(group_id, member_agent_id, peer_id=peer_id)
        if not ok:
            raise ValueError(f"cannot add member: unknown group {group_id}")
        return {"group_id": group_id, "member_agent_id": member_agent_id, "added": True}

    def group_remove_member(self, group_id: str, member_agent_id: str, *, session_id: str | None = None) -> dict:
        ok = self._group_store().remove_member(group_id, member_agent_id)
        if not ok:
            raise ValueError(f"cannot remove member: unknown group or member {group_id}/{member_agent_id}")
        return {"group_id": group_id, "member_agent_id": member_agent_id, "removed": True}

    def group_delete(self, group_id: str, *, session_id: str | None = None) -> dict:
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        owner = rec.agent_id or rec.peer_id
        ok = self._group_store().delete_group(group_id, owner_agent_id=owner)
        if not ok:
            raise ValueError(f"cannot delete group {group_id}: not found or not owned by {owner}")
        return {"group_id": group_id, "deleted": True}

    def broadcast_send(
        self,
        group_id: str,
        content: str,
        *,
        session_id: str | None = None,
    ) -> dict:
        """Broadcast one message to every member's live session (P4).

        Persist-parent-first, deterministic per-recipient children, bounded
        concurrency, explicit partial results (G3.5/G3.6).
        """
        from agent_peer.broadcast import BroadcastEngine

        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        sender_agent = rec.agent_id or rec.peer_id
        sender_peer = rec.peer_id
        groups = self._group_store()
        engine = BroadcastEngine(
            self._store,
            groups,
            send=self._broadcast_send_one(sender_peer),
            resolve=self._broadcast_resolve,
            concurrency=self._config.fanout_concurrency,
            ttl_seconds=self._config.broadcast_ttl_seconds,
        )
        bid = engine.create_broadcast(sender_agent, group_id, content)
        result = engine.fan_out(bid)
        return {"broadcast_id": result.broadcast_id, "summary": result.summary, "per_member": result.per_member}

    def _broadcast_send_one(self, sender_peer_id: str):
        """Build a send callback bound to the exact invoking session (F-03)."""

        def _send(agent_id, peer_id, content, *, child_message_id=None) -> dict:
            from agent_peer.models import Kind, PeerIdentity, make_envelope

            env = make_envelope(
                sender=PeerIdentity(peer_id=sender_peer_id, name="broadcast", profile=""),
                recipient_peer_id=peer_id,
                kind=Kind.MESSAGE,
                content=content,
            )
            receipt = self._runtime.send(env)
            return {"state": receipt.state.value, "detail": receipt.detail}

        return _send

    def _broadcast_resolve(self, agent_id, pin=None):
        """Resolve an agent to its live primary session (G2.5)."""
        try:
            record = self._discovery.resolve_agent(agent_id, pinned_peer_id=pin)
            return record
        except Exception:  # noqa: BLE001 - fail closed to unreachable
            return None

    def doctor(self) -> dict:
        """Diagnostics for `hermes peer doctor` (REL-1104, P6.3/G1.4).

        Combines the v1 seam/runtime facts with the content-free health
        snapshot (backend, peers, store, groups, requests, stale state),
        metrics and actionable remedies.
        """
        from agent_peer.groups import GroupStore
        from agent_peer.health import health_snapshot
        from agent_peer.requests import RequestStore

        from .plugin import host_seam_supported

        # Stale count is read-only here (never a side-effectful repair in
        # doctor): registry heartbeat staleness, not mutation.
        stale = len(self._registry.stale_candidates())
        groups = GroupStore(self._store)
        requests = RequestStore(self._store)
        health = health_snapshot(
            backend_kind=self._runtime._backend.kind,
            runtime_dir=self._paths.root,
            registry_entries=len(self._registry.list_peers()),
            local_sessions=len(self._peers),
            live_peers=len(self._discovery.list_live_peers()),
            pending_messages=self._store.count_all(),
            groups=len(groups.list_groups()),
            active_requests=requests.count_active(),
            stale_count=stale,
            store_ok=True,
            metrics=self._metrics.snapshot(),
        )
        return {
            "seam_supported": host_seam_supported(self._ctx),
            "runtime_dir": str(self._paths.root),
            "registry_entries": health["registry_entries"],
            "local_sessions": health["local_sessions"],
            "live_peers": health["live_peers"],
            "pending_messages": health["pending_messages"],
            "groups": health["groups"],
            "active_requests": health["active_requests"],
            "stale_count": health["stale_count"],
            "backend": health["backend"],
            "policy": self._policy.policy.value,
            "metrics": health["metrics"],
            "problems": health["problems"],
            "ok": health["ok"] and host_seam_supported(self._ctx) and not self._paths.root.is_symlink(),
        }

    def metrics_snapshot(self) -> dict:
        """Content-free metrics for Desktop/status (P6.1, G1.1)."""
        return self._metrics.snapshot()

    def subscribe_events(self) -> int:
        """Bounded event subscription for Desktop acceleration (G1.8)."""
        return self._events.subscribe()

    def unsubscribe_events(self, sid: int) -> None:
        self._events.unsubscribe(sid)

    def drain_events(self, sid: int) -> list[dict]:
        return self._events.drain(sid)

    def _envelope_from_row(self, row: dict) -> Envelope:
        """Rebuild an Envelope from a stored row (for release)."""
        from datetime import datetime

        from agent_peer.models import make_envelope

        return make_envelope(
            sender=PeerIdentity(peer_id=row["sender_peer_id"], name="peer", profile=""),
            recipient_peer_id=row["recipient_peer_id"],
            kind=Kind(row["kind"]),
            content=row["content"],
            reply_to=row.get("reply_to"),
            conversation_id=row.get("conversation_id"),
            hop_count=row.get("hop_count", 0),
            message_id=row["message_id"],
            ttl_seconds=1,
            now=datetime.fromisoformat(row["created_at"]),
        )
