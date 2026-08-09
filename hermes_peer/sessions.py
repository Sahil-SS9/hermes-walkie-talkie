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
        self._carry_alias: str | None = None  # explicit alias across rotation
        self._policy = PolicyEngine(policy=self._config.inbound)
        self._session_policies: dict[str, Policy] = {}  # peer_id -> session-scoped policy

    # ------------------------------------------------------------------
    # Lifecycle hooks (fired by Hermes with explicit kwargs — never
    # inherited thread context, HP-704).
    # ------------------------------------------------------------------

    def on_session_start(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        surface = _surface_of(platform)
        existing = self._session_to_peer.get(session_id)
        if existing is not None:
            # Same session already registered: mark working again.
            self._registry.update_presence(existing, Presence.WORKING)
            return
        meta = host_metadata()
        peer_id = generate_peer_id()
        alias = self._aliases.effective_name(peer_id, default_base=os.path.basename(os.getcwd()) or "session")
        record = PeerRecord(
            peer_id=peer_id,
            instance_id=generate_instance_id(),
            session_id=session_id,
            name=alias,
            profile=kwargs.get("profile", ""),
            surface=surface,
            host_target=host_target_for(surface, session_id),
            pid=meta["pid"],
            cwd=meta["cwd"],
            git_repo_root=meta["git_repo_root"],
            git_branch=meta["git_branch"],
            started_at=meta["started_at"],
            last_seen=meta["started_at"],
            status=Presence.WORKING.value,
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
        if self._carry_alias:
            carried, self._carry_alias = self._carry_alias, None
            self.set_alias(carried)
        logger.info("hermes-peer: registered peer %s (%s) on %s", bound.name, bound.peer_id, surface)

    def on_session_end(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        peer_id = self._session_to_peer.get(session_id)
        if peer_id is not None:
            self._registry.update_presence(peer_id, Presence.IDLE)

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
        peer_id = self._session_to_peer.pop(old_session, None)
        if peer_id is not None:
            handle = self._peer_handles.pop(peer_id, None)
            if handle is not None:
                handle.close()
            old_record = self._peers.pop(old_session, None)
            self._session_policies.pop(peer_id, None)
            if old_record is not None and old_record.name:
                explicit = self._aliases.get_alias(old_record.peer_id)
                if explicit:
                    # Carry the explicit alias forward to the rotated session.
                    self._carry_alias = explicit
        self.on_session_start(new_session, platform=platform, **kwargs)

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
        requesting = None
        if not include_self:
            # Exclude every peer this process owns (all registered sessions).
            requesting = next(iter(self._peer_handles), None)
        return list(self._discovery.list_live_peers(requesting_peer_id=requesting))

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
        import dataclasses

        # Backwards-compatible single-session fallback: when exactly one
        # session is registered and none is named, use it (documented).
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        rec = self._require_session(session_id)
        self._aliases.set_alias(rec.peer_id, name)
        renamed = dataclasses.replace(rec, name=name)
        # Preserve the canonical bound socket/instance authority (F-02).
        self._registry.register(renamed)
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
        """
        engine = self._policy_engine_for(envelope.recipient_peer_id)
        engine.register_pending(envelope.recipient_peer_id, self._store.count_pending(envelope.recipient_peer_id))
        decision = engine.evaluate(envelope)
        state = decision.state.value

        if decision.action == "drop":
            self._store.record(
                {
                    "message_id": envelope.message_id,
                    "recipient_peer_id": envelope.recipient_peer_id,
                    "sender_peer_id": envelope.sender.peer_id,
                    "kind": envelope.kind.value,
                    "content": "",
                    "state": state,
                    "created_at": envelope.created_at.isoformat(),
                    "expires_at": envelope.expires_at.isoformat(),
                    "reply_to": envelope.reply_to,
                    "conversation_id": envelope.conversation_id,
                    "delivered_at": None,
                    "hop_count": envelope.hop_count,
                }
            )
            return decision.state

        if decision.action == "refuse":
            self._store.record(
                {
                    "message_id": envelope.message_id,
                    "recipient_peer_id": envelope.recipient_peer_id,
                    "sender_peer_id": envelope.sender.peer_id,
                    "kind": envelope.kind.value,
                    "content": "",  # minimal audit metadata only (AP-606)
                    "state": ReceiptState.REFUSED.value,
                    "created_at": envelope.created_at.isoformat(),
                    "expires_at": envelope.expires_at.isoformat(),
                    "reply_to": envelope.reply_to,
                    "conversation_id": envelope.conversation_id,
                    "delivered_at": None,
                    "hop_count": envelope.hop_count,
                }
            )
            return ReceiptState.REFUSED

        if decision.action == "hold":
            self._store.record(
                {
                    "message_id": envelope.message_id,
                    "recipient_peer_id": envelope.recipient_peer_id,
                    "sender_peer_id": envelope.sender.peer_id,
                    "kind": envelope.kind.value,
                    "content": envelope.content,
                    "state": ReceiptState.HELD.value,
                    "created_at": envelope.created_at.isoformat(),
                    "expires_at": envelope.expires_at.isoformat(),
                    "reply_to": envelope.reply_to,
                    "conversation_id": envelope.conversation_id,
                    "delivered_at": None,
                    "hop_count": envelope.hop_count,
                }
            )
            return ReceiptState.HELD

        # accept: forward to the harness; queued only after host acceptance.
        from .delivery import DeliveryAdapter

        accepted = DeliveryAdapter(self._ctx, self).deliver(envelope)
        return ReceiptState.QUEUED if accepted else ReceiptState.HELD

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
        import dataclasses

        self._aliases.set_alias(peer_id, name)
        record = self._registry.get(peer_id)
        if record is not None:
            renamed = dataclasses.replace(record, name=name)
            self._registry.register(renamed)
            for session_id, rec in self._peers.items():
                if rec.peer_id == peer_id:
                    self._peers[session_id] = renamed

    def doctor(self) -> dict:
        """Diagnostics for `hermes peer doctor` (REL-1104)."""
        from .plugin import host_seam_supported

        return {
            "seam_supported": host_seam_supported(self._ctx),
            "runtime_dir": str(self._paths.root),
            "registry_entries": len(self._registry.list_peers()),
            "local_sessions": len(self._peers),
            "policy": self._policy.policy.value,
            "ok": host_seam_supported(self._ctx) and not self._paths.root.is_symlink(),
        }

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
