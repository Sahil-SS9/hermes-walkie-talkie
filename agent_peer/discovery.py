"""Harness-neutral cross-process peer discovery (F-01, REM-108..REM-111).

The historical ``peer_list_agents`` / ``/peers`` filtered registry contents
through ``PeerRuntimeManager._peer_handles`` — the in-process connection map —
so records published by a sibling process were never listed. This module
implements the corrected contract:

- ``list_live_peers`` reads a captured snapshot of every parseable registry
  record under the shared owner-local runtime root, validates it, and probes
  each candidate through its recorded Unix socket with the DISCOVER/ALIVE
  challenge-response (bounded timeouts, ``secrets`` nonce, exact identity
  comparison). It NEVER filters through local connection maps, NEVER deletes
  or rewrites registry/socket files, and returns an immutable tuple stably
  sorted by ``(name.casefold(), peer_id)``.
- ``resolve_peer`` performs fail-closed target resolution: exact ``peer_id``,
  exact live ``session_id``, ``name~<short-peer-id>``, or a bare name that
  must resolve to exactly one live peer. Collisions return every candidate
  with full disambiguation metadata.
- ``repair_stale`` is the separate, explicit, race-safe cleanup path: it
  re-reads and compares peer/instance/registry-inode/socket-inode
  immediately before mutation and refuses to delete a replaced socket or
  ambiguous record. Listing itself never mutates.

The protocol is the existing agent-peer/1 framed Unix transport: DISCOVER and
ALIVE are protocol-v1 control kinds (see agent_peer.models.Kind). No TCP,
no cloud, no daemon.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import uuid as uuidlib
from datetime import UTC, datetime
from pathlib import Path

from .backends.base import TransportEndpoint  # noqa: E402
from .codec import decode_envelope, encode_envelope
from .constants import PROTOCOL_ID
from .errors import AgentPeerError
from .models import Envelope, Kind, PeerIdentity, PeerRecord
from .paths import RuntimePaths, select_runtime_dir
from .registry import Registry

logger = logging.getLogger("agent_peer.discovery")

_DISCOVER_TIMEOUT = 1.0  # bounded probe budget (seconds)


class DiscoveryError(AgentPeerError):
    """Base for discovery failures (fail-closed)."""


class AmbiguousPeer(DiscoveryError):
    """A target resolved to more than one live peer."""


class InvalidProbe(DiscoveryError):
    """A probe returned a malformed or mismatched identity."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_record(
    path: Path,
    paths: RuntimePaths,
    *,
    require_socket: bool = True,
) -> PeerRecord | None:
    """Parse one registry file into a PeerRecord, or None when invalid.

    Validation: filename must equal ``<peer_id>.json``, the embedded peer_id
    must match the filename, the socket path must be contained under the
    runtime root or its (possibly relocated) sockets dir, and the record must
    construct (protocol validated).
    """
    if path.suffix != ".json":
        return None
    peer_id_from_name = path.stem
    record = Registry(paths).get(peer_id_from_name)
    if record is None:
        return None
    if record.peer_id != peer_id_from_name:
        logger.warning("discovery: registry filename/peer_id mismatch at %s", path)
        return None
    if record.socket_path:
        sock = Path(record.socket_path)
        # Safe containment: the socket must live under the runtime root's
        # sockets dir (which may relocate to a short /tmp path when the root
        # is deep — see RuntimePaths).
        try:
            sock_resolved = sock.resolve()
            root_resolved = paths.root.resolve()
            sockets_resolved = paths.sockets_dir.resolve()
            if not (
                root_resolved in sock_resolved.parents
                or sockets_resolved in sock_resolved.parents
                or sock_resolved.parent == sockets_resolved
            ):
                logger.warning("discovery: socket outside runtime root: %s", sock)
                return None
        except OSError:
            return None
        expected = paths.socket_path_for(record.peer_id, record.instance_id)
        if sock != expected:
            logger.warning("discovery: socket path does not match peer instance: %s", sock)
            return None
        try:
            sock_st = sock.lstat()
        except FileNotFoundError:
            return None if require_socket else record
        except OSError:
            return None
        if not stat.S_ISSOCK(sock_st.st_mode):
            return None
        if sock_st.st_uid != os.geteuid() or stat.S_IMODE(sock_st.st_mode) & 0o077:
            logger.warning("discovery: refusing non-owner-only socket %s", sock)
            return None
        if record.socket_uid != sock_st.st_uid or record.socket_inode != sock_st.st_ino:
            logger.warning("discovery: socket authority mismatch for %s", record.peer_id)
            return None
    return record


def _probe_once(record: PeerRecord, backend=None) -> dict | None:
    """Run the DISCOVER/ALIVE challenge against one record's socket.

    Returns the verified identity dict (nonce, peer_id, instance_id,
    session_id, protocol, status) or None when the probe fails closed.
    The nonce is generated with ``secrets``, is single-use per probe, and is
    compared exactly against the ALIVE reply.

    ``backend`` is the transport backend (defaults to the platform auto
    selection); pass an explicit backend in tests to isolate platform
    behaviour.
    """
    if backend is None:
        from .backends import get_transport_backend

        backend = get_transport_backend()
    if not record.socket_path:
        return None
    nonce = secrets.token_hex(16)
    probe_id = str(uuidlib.uuid4())
    now = datetime.now(UTC)
    request = Envelope(
        protocol=PROTOCOL_ID,
        message_id=probe_id,
        created_at=now,
        expires_at=now + timedelta(seconds=30),
        sender=PeerIdentity(peer_id="00000000-0000-0000-0000-000000000000", name="discovery", profile=""),
        recipient_peer_id=record.peer_id,
        kind=Kind.DISCOVER,
        content="discover",
        reply_to=None,
        conversation_id=nonce,
        hop_count=0,
    )
    try:
        payload = encode_envelope(request).encode("utf-8")
        reply_payload = backend.request(
            TransportEndpoint(kind="unix", address=record.socket_path),
            payload,
            timeout=_DISCOVER_TIMEOUT,
        )
        reply = decode_envelope(reply_payload)
    except (OSError, AgentPeerError):
        return None
    if reply.kind is not Kind.ALIVE:
        return None
    if reply.conversation_id != nonce or reply.sender.peer_id != record.peer_id:
        return None
    try:
        identity = json.loads(reply.content)
    except json.JSONDecodeError:
        return None
    if not isinstance(identity, dict):
        return None
    # Exact nonce comparison.
    if identity.get("nonce") != nonce:
        return None
    # Exact identity comparison.
    if identity.get("peer_id") != record.peer_id:
        return None
    if identity.get("instance_id") != record.instance_id:
        return None
    if identity.get("session_id") != record.session_id:
        return None
    # V2 fields: when the record advertises them, the ALIVE reply must match
    # exactly; absent fields (V1 peers) are tolerated on both sides.
    if identity.get("agent_id") != record.agent_id:
        return None
    if tuple(identity.get("protocols") or ()) != record.protocols:
        return None
    if identity.get("protocol") != record.protocol:
        return None
    if identity.get("status") != record.status:
        return None
    return identity


class DiscoveryService:
    """Read-only cross-process discovery over the shared runtime root."""

    def __init__(
        self,
        runtime_root: Path | RuntimePaths | None = None,
        registry: Registry | None = None,
        backend=None,
        path_backend=None,
    ) -> None:
        from .backends import get_transport_backend
        from .platform_paths import get_path_backend

        self._paths = runtime_root if isinstance(runtime_root, RuntimePaths) else RuntimePaths(runtime_root or select_runtime_dir())
        self._registry = registry or Registry(self._paths)
        self._backend = backend or get_transport_backend()
        self._path_backend = path_backend or get_path_backend()

    # -- listing ---------------------------------------------------------

    def _snapshot(self, *, require_socket: bool = True) -> list[PeerRecord]:
        """Captured snapshot of all parseable registry records (read-only)."""
        records: list[PeerRecord] = []
        for path in sorted(self._paths.registry_dir.glob("*.json")):
            record = _parse_record(path, self._paths, require_socket=require_socket)
            if record is not None:
                records.append(record)
        return records

    def list_live_peers(
        self,
        requesting_peer_id: str | None = None,
        *,
        requesting_peer_ids: set[str] | frozenset[str] | None = None,
    ) -> tuple[PeerRecord, ...]:
        """Return every LIVE (probed) peer as an immutable sorted tuple.

        Never filters through local connection maps, never mutates the
        registry or sockets. Stable sort: ``(name.casefold(), peer_id)``.
        """
        excluded = set(requesting_peer_ids or ())
        if requesting_peer_id is not None:
            excluded.add(requesting_peer_id)
        live: list[PeerRecord] = []
        for record in self._snapshot():
            if record.peer_id in excluded:
                continue
            identity = _probe_once(record)
            if identity is None:
                continue
            # Re-read the record AFTER the probe to catch a replacement
            # (TOCTOU fence for listing).
            fresh = _parse_record(self._paths.registry_file_for(record.peer_id), self._paths)
            if fresh is None or fresh != record:
                continue
            live.append(fresh)
        live.sort(key=lambda r: (r.name.casefold(), r.peer_id))
        return tuple(live)

    # -- fail-closed target resolution (REM-110) -------------------------

    def resolve_peer(self, target: str, requesting_peer_id: str | None = None) -> tuple[PeerRecord | None, dict | None]:
        """Resolve *target* to a live peer record; ``(record, None)`` or
        ``(None, error-dict)``. Never picks the first match on ambiguity.

        Resolution order:
        1. exact full ``peer_id`` (when live);
        2. exact live ``session_id`` (fenced to its peer);
        3. ``name~<short-peer-id>`` preferred human handle;
        4. bare name resolves only when exactly one live peer has it;
        5. duplicate names return every candidate with full metadata.
        """
        if not target:
            return None, {"error": "empty target"}
        # 1. Exact peer_id.
        if _looks_like_uuid(target):
            record = _parse_record(self._paths.registry_file_for(target), self._paths)
            if record is not None and self._probe(record):
                return record, None
            return None, {"error": f"no live peer with peer_id {target!r}"}
        # 2. Exact live session_id.
        for record in self.list_live_peers(requesting_peer_id=requesting_peer_id):
            if record.session_id == target:
                return record, None
        # 3. name~shortID.
        if "~" in target:
            name, _, short = target.partition("~")
            candidates = [r for r in self.list_live_peers(requesting_peer_id=requesting_peer_id) if r.name == name]
            exact = [r for r in candidates if r.peer_id.startswith(short)]
            if len(exact) == 1:
                return exact[0], None
            if len(exact) > 1:
                return None, self._collision_error(name, candidates)
            return None, {"error": f"no live peer matching {target!r}"}
        # 4/5. Bare name.
        candidates = [r for r in self.list_live_peers(requesting_peer_id=requesting_peer_id) if r.name == target]
        if not candidates:
            return None, {"error": f"no reachable peer named or identified by {target!r}"}
        if len(candidates) == 1:
            return candidates[0], None
        return None, self._collision_error(target, candidates)

    def _collision_error(self, name: str, candidates: list[PeerRecord]) -> dict:
        rows = []
        for r in sorted(candidates, key=lambda r: (r.name.casefold(), r.peer_id)):
            rows.append(
                {
                    "name": r.name,
                    "peer_id": r.peer_id,
                    "short_peer_id": r.peer_id[:8],
                    "session_id": r.session_id,
                    "profile": r.profile,
                    "surface": r.surface,
                    "cwd": r.cwd,
                    "git_repo_root": r.git_repo_root,
                    "git_branch": r.git_branch,
                    "status": r.status,
                }
            )
        return {
            "error": f"ambiguous target {name!r}: {len(candidates)} peers share this name",
            "candidates": rows,
        }

    def _probe(self, record: PeerRecord) -> bool:
        return _probe_once(record, backend=self._backend) is not None

    # -- deterministic agent -> peer resolution (P3.7, G2.5) ----------------

    def resolve_agent(
        self,
        agent_id: str,
        *,
        pinned_peer_id: str | None = None,
        requesting_peer_id: str | None = None,
    ) -> PeerRecord:
        """Resolve an agent target to exactly one live session (G2.5).

        Order:
        1. pinned live ``peer_id`` -> that session;
        2. exactly one explicitly primary session -> that session;
        3. exactly one live session -> that session;
        4. else -> raise :class:`AmbiguousPeer` (never broadcast to all).

        A record with an empty ``agent_id`` is V1-only and never resolvable by
        agent. Raises ``DiscoveryError`` subclasses; never picks the first
        match on ambiguity (G2.6).
        """
        if not agent_id:
            raise DiscoveryError("empty agent_id")
        excluded = set()
        if requesting_peer_id:
            excluded.add(requesting_peer_id)
        candidates = [
            r
            for r in self._registry.list_peers()
            if r.agent_id == agent_id and r.peer_id not in excluded
        ]
        live = [r for r in candidates if self._probe(r)]
        if not live:
            raise DiscoveryError(f"no live session for agent {agent_id!r}")

        # 1. Pinned live peer_id wins when it is one of the live sessions.
        if pinned_peer_id:
            pinned = [r for r in live if r.peer_id == pinned_peer_id]
            if len(pinned) == 1:
                return pinned[0]
            raise AmbiguousPeer(
                f"pinned peer {pinned_peer_id!r} is not a live session of agent {agent_id!r}"
            )

        # 2. Exactly one explicitly primary session wins.
        primaries = [r for r in live if r.capabilities.get("primary") is True]
        if len(primaries) == 1:
            return primaries[0]

        # 3. Exactly one live session wins.
        if len(live) == 1:
            return live[0]

        # 4. Ambiguous: fail closed, no delivery.
        raise AmbiguousPeer(
            f"agent {agent_id!r} has {len(live)} live sessions; "
            "pin a peer_id or mark one session primary"
        )

    # -- separate race-safe stale repair (REM-111) ------------------------

    def repair_stale(self, runtime_root: Path | None = None, now: datetime | None = None) -> list[PeerRecord]:
        """Explicit, separate cleanup of stale records.

        Listing is read-only and never calls this. Repair only runs via an
        explicit doctor/repair action or bounded startup/teardown paths.

        For each candidate (stale heartbeat or dead socket):
        1. capture the stale candidate identity and file/socket metadata;
        2. run the exact liveness challenge;
        3. re-read and compare peer ID, instance ID, registry inode and
           socket inode immediately before mutation;
        4. refuse cleanup if any value changed or liveness is ambiguous;
        5. unlink only the exact stale record/socket proved by the fence.
        """
        from .constants import STALE_THRESHOLD

        now = now or datetime.now(UTC)
        removed: list[PeerRecord] = []
        for record in self._snapshot(require_socket=False):
            # Only stale candidates are considered.
            last_seen = _parse_iso(record.last_seen)
            if last_seen is not None and (now - last_seen) <= timedelta(seconds=STALE_THRESHOLD) and self._probe(record):
                # Fresh heartbeat and live: keep it.
                continue
            # Stale OR dead-probe: fence before mutating.
            self._fenced_remove(record, removed)
        return removed

    def _fenced_remove(self, record: PeerRecord, removed: list[PeerRecord]) -> None:
        reg_path = self._paths.registry_file_for(record.peer_id)
        sock_path = Path(record.socket_path) if record.socket_path else None
        try:
            reg_st = reg_path.stat()
            sock_st = sock_path.stat() if sock_path is not None and sock_path.exists() else None
        except OSError:
            return
        # Re-read the record immediately before mutation.
        fresh = self._registry.get(record.peer_id)
        if fresh is None:
            return
        if fresh.instance_id != record.instance_id:
            logger.warning("discovery: repair refused (instance changed) for %s", record.peer_id)
            return
        if fresh.socket_path != record.socket_path:
            logger.warning("discovery: repair refused (socket path changed) for %s", record.peer_id)
            return
        if reg_st.st_ino != reg_path.stat().st_ino:
            logger.warning("discovery: repair refused (registry inode changed) for %s", record.peer_id)
            return
        if sock_st is not None and sock_path is not None:
            try:
                if sock_path.stat().st_ino != sock_st.st_ino:
                    logger.warning("discovery: repair refused (socket inode changed) for %s", record.peer_id)
                    return
            except OSError:
                return
        # Liveness challenge one more time before mutation.
        if self._probe(record):
            return
        # NG-07 fence: a path must never be unlinked while an untracked live
        # listener remains bound to it. Even when the record's identity probe
        # fails (e.g. forged instance), if the socket path still accepts a
        # connection, a genuine peer is bound there — refuse cleanup entirely.
        if sock_path is not None and sock_path.exists() and self._backend.bound(
            TransportEndpoint(kind="unix", address=str(sock_path)),
            timeout=_DISCOVER_TIMEOUT,
        ):
            logger.warning("discovery: repair refused (live listener on %s) for %s", sock_path, record.peer_id)
            return
        # Fence passed: unlink the exact stale record (and socket if present).
        try:
            reg_path.unlink()
        except FileNotFoundError:
            return
        if sock_path is not None:
            try:
                sock_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("discovery: could not unlink stale socket %s", sock_path)
        removed.append(record)


def _socket_bound(path: Path) -> bool:
    """True when a live listener is bound at *path* (accepts connections).

    Backend-delegating shim retained for V1 module-surface compatibility;
    production callers use ``DiscoveryService._backend.bound`` directly.
    """
    from .backends import get_transport_backend

    backend = get_transport_backend()
    return backend.bound(
        TransportEndpoint(kind="unix", address=str(path)),
        timeout=_DISCOVER_TIMEOUT,
    )


def _looks_like_uuid(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value))


def _parse_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


from datetime import timedelta  # noqa: E402 - used in repair_stale

__all__ = [
    "AmbiguousPeer",
    "DiscoveryError",
    "DiscoveryService",
    "InvalidProbe",
]
