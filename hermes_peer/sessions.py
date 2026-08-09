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

from agent_peer.identity import AliasStore, generate_instance_id, generate_peer_id, host_metadata
from agent_peer.models import Envelope, Kind, PeerIdentity, PeerRecord, Presence
from agent_peer.paths import RuntimePaths, select_runtime_dir, select_state_dir
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
        self._peers: dict[str, PeerRecord] = {}  # session_id -> record
        self._session_to_peer: dict[str, str] = {}  # session_id -> peer_id
        self._peer_handles: dict[str, PeerHandle] = {}
        self._carry_alias: str | None = None  # explicit alias across rotation

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
        self._peers[session_id] = record
        self._session_to_peer[session_id] = record.peer_id
        self._peer_handles[record.peer_id] = handle
        if self._carry_alias:
            carried, self._carry_alias = self._carry_alias, None
            self.set_alias(carried)
        logger.info("hermes-peer: registered peer %s (%s) on %s", record.name, record.peer_id, surface)

    def on_session_end(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        peer_id = self._session_to_peer.get(session_id)
        if peer_id is not None:
            self._registry.update_presence(peer_id, Presence.IDLE)

    def on_session_reset(self, session_id: str, platform: str | None = None, **kwargs) -> None:
        """Session rotation: close existing registrations, register the new id.

        The hook carries the NEW session id; a CLI process owns one peer, so
        v1 closes every registration owned by this process before registering
        the rotated session. The alias and inbox state survive; the stale
        host target is never reused (HP-709).
        """
        for old_session in list(self._session_to_peer.keys()):
            peer_id = self._session_to_peer.pop(old_session, None)
            if peer_id is None:
                continue
            handle = self._peer_handles.pop(peer_id, None)
            if handle is not None:
                handle.close()
            old_record = self._peers.pop(old_session, None)
            if old_record is not None and old_record.name:
                explicit = self._aliases.get_alias(old_record.peer_id)
                if explicit:
                    # Carry the explicit alias forward to the rotated session.
                    self._carry_alias = explicit
        self.on_session_start(session_id, platform=platform, **kwargs)

    def on_session_finalize(self, session_id: str, platform: str | None = None, reason: str = "shutdown", **kwargs) -> None:
        peer_id = self._session_to_peer.pop(session_id, None)
        if peer_id is None:
            return
        handle = self._peer_handles.pop(peer_id, None)
        if handle is not None:
            handle.close()
        self._peers.pop(session_id, None)
        logger.info("hermes-peer: removed peer for session %s (%s)", session_id, reason)

    def shutdown(self) -> None:
        for session_id in list(self._session_to_peer.keys()):
            self.on_session_finalize(session_id, reason="plugin_shutdown")
        self._runtime.shutdown()
        self._store.close()

    # ------------------------------------------------------------------
    # Public surface used by tools/commands (P8)
    # ------------------------------------------------------------------

    def list_peers(self) -> list[PeerRecord]:
        return self._registry.list_peers()

    def set_alias(self, name: str) -> None:
        """Persist an alias for THIS process's first registered peer."""
        import dataclasses

        if not self._peers:
            raise ValueError("no active peer session to name")
        first = next(iter(self._peers.values()))
        self._aliases.set_alias(first.peer_id, name)
        renamed = dataclasses.replace(first, name=name)
        self._registry.register(renamed)
        self._peers[first.session_id] = renamed

    def peer_id_for_session(self, session_id: str) -> str | None:
        return self._session_to_peer.get(session_id)

    def resolve_peer(self, peer_id: str) -> PeerRecord | None:
        return self._registry.get(peer_id)

    def _make_envelope(self, *, recipient: str, content: str, reply_to: str | None = None, kind: Kind = Kind.MESSAGE, conversation_id: str | None = None) -> Envelope:
        """Build a validated outbound envelope from this peer's identity."""
        if not self._peers:
            raise ValueError("no active peer session")
        first = next(iter(self._peers.values()))
        sender = PeerIdentity(peer_id=first.peer_id, name=first.name, profile=first.profile)
        from agent_peer.models import make_envelope

        return make_envelope(
            sender=sender,
            recipient_peer_id=recipient,
            kind=kind,
            content=content,
            reply_to=reply_to,
            conversation_id=conversation_id,
        )

    def _on_inbound(self, envelope: Envelope):
        """Delivery handler wired into the runtime: forward to the host."""
        from .delivery import DeliveryAdapter

        DeliveryAdapter(self._ctx, self).deliver(envelope)
        from agent_peer.models import ReceiptState

        return ReceiptState.QUEUED
