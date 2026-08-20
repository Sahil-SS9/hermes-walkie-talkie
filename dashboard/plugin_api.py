"""Hermes Peer dashboard plugin — backend API routes (P8.1..P8.3, G6.3).

Mounted at /api/plugins/hermes-peer/ by the dashboard plugin system.

Every route is a thin wrapper over the process-local PeerSessionManager
(``hermes_peer.plugin.get_manager``) — the same code path the tools/commands
use, so the three surfaces cannot drift. Reads return content-free
metadata + the same bounded data the tools expose; nothing here reads
SQLite or registry files directly from the renderer (G6.6).

Security: HTTP routes pass the dashboard's session-token auth middleware;
the /events WebSocket uses the canonical ``_ws_auth_ok`` gate (delegated,
same as the kanban plugin) so OAuth/loopback modes all work.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from agent_peer.models import Policy

log = logging.getLogger(__name__)

router = APIRouter()

MANAGER_IMPORT_ERROR = "hermes-peer is not active in this process"


def _manager():
    """Resolve the process-local manager; raise 503 when inactive."""
    try:
        from hermes_peer.plugin import get_manager
    except Exception as exc:  # pragma: no cover - plugin import path
        raise HTTPException(status_code=503, detail=MANAGER_IMPORT_ERROR) from exc
    mgr = get_manager()
    if mgr is None:
        raise HTTPException(status_code=503, detail=MANAGER_IMPORT_ERROR)
    return mgr


def _ws_upgrade_authorized(ws: WebSocket) -> bool:
    """Delegate to the dashboard's canonical WS auth gate (G6.7).

    Fails closed (RISKY-1): if the auth module cannot be imported or the
    delegate raises, the upgrade is REJECTED. A broken production import
    must never become an authentication bypass. Tests inject the auth
    decision by monkeypatching this function or the delegate module.
    """
    try:
        import importlib

        _ws = importlib.import_module("hermes_cli.web_server")
    except Exception:
        log.error("hermes_cli.web_server import failed; rejecting WS upgrade (fail closed)")
        return False
    try:
        return bool(_ws._ws_auth_ok(ws))
    except Exception:
        log.error("WS auth delegate raised; rejecting WS upgrade (fail closed)")
        return False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    mgr = _manager()
    return mgr.doctor()


@router.get("/metrics")
def metrics() -> dict:
    mgr = _manager()
    return mgr.metrics_snapshot()


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------


@router.get("/peers")
def peers() -> dict:
    mgr = _manager()
    rows = []
    for record in mgr.list_peers():
        rows.append(
            {
                "peer_id": record.peer_id,
                "agent_id": record.agent_id,
                "name": record.name,
                "profile": record.profile,
                "surface": record.surface,
                "status": record.status,
                "current_activity": record.current_activity,
                "cwd": record.cwd,
                "git_branch": record.git_branch,
            }
        )
    return {"peers": rows}


@router.get("/peers/summary")
def peers_summary() -> dict:
    """Aggregate presence summary (G2/G5/G6): active/offline counts, the
    local ``you_peer_id`` and the newest heartbeat timestamp. Offline is
    derived at this layer; no status mutation ever happens here."""
    mgr = _manager()
    return mgr.summary()


# ---------------------------------------------------------------------------
# Groups + broadcasts
# ---------------------------------------------------------------------------


@router.get("/groups")
def groups() -> dict:
    mgr = _manager()
    return {"groups": mgr.group_list()}


@router.post("/groups")
def create_group(body: dict) -> dict:
    mgr = _manager()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    return mgr.group_create(name)


@router.get("/groups/{group_id}/members")
def group_members(group_id: str) -> dict:
    mgr = _manager()
    return {"group_id": group_id, "members": mgr.group_members_list(group_id)}


@router.post("/groups/{group_id}/members")
def add_member(group_id: str, body: dict) -> dict:
    mgr = _manager()
    agent_id = (body.get("agent_id") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    return mgr.group_add_member(group_id, agent_id)


@router.get("/broadcasts/{broadcast_id}")
def broadcast_outcomes(broadcast_id: str) -> dict:
    """Per-recipient broadcast outcomes (P8.6, G6.4)."""
    mgr = _manager()
    out = mgr.broadcast_outcomes(broadcast_id)
    if not out["per_member"]:
        raise HTTPException(status_code=404, detail=f"unknown broadcast {broadcast_id}")
    return out


# ---------------------------------------------------------------------------
# Inbox + requests
# ---------------------------------------------------------------------------


@router.get("/inbox")
def inbox(session_id: str | None = None) -> dict:
    mgr = _manager()
    try:
        return {"messages": mgr.session_inbox(session_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/requests")
def requests(session_id: str | None = None) -> dict:
    mgr = _manager()
    try:
        return {"requests": mgr.session_requests(session_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/requests/{request_id}")
def request_detail(request_id: str, session_id: str | None = None) -> dict:
    mgr = _manager()
    # Validate the session selection first so a multi-session host cannot
    # fall back to first-peer silently (RISKY-2).
    try:
        mgr.resolve_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return mgr.request_status(request_id, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/requests/{request_id}/respond")
def respond(request_id: str, body: dict, session_id: str | None = None) -> dict:
    mgr = _manager()
    try:
        mgr.resolve_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    action = (body.get("action") or "").strip()
    if action not in ("accept", "progress", "complete", "fail", "refuse"):
        raise HTTPException(status_code=400, detail=f"invalid action {action!r}")
    try:
        return mgr.request_respond(request_id, action, detail=body.get("detail") or "", session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Peer actions (G8): send + policy — thin wrappers over the same manager
# methods the tools/commands call. peer_id is the TARGET (recipient for send,
# existence check for policy); the sender/policy subject is always THIS
# process's own local session (single-session default), matching the
# peer-send / peer-policy commands. The target's owning session belongs to a
# sibling process and is never resolved locally.
# ---------------------------------------------------------------------------


@router.post("/peers/{peer_id}/messages")
def peer_send(peer_id: str, body: dict, session_id: str | None = None) -> dict:
    """Send one message to a peer (G8 'Send'; peer-send equivalent).

    ``peer_id`` is the RECIPIENT; the sender is this process's own local
    session (single-session default, same as the peer-send command). The
    target's owning session is NOT resolved locally — it belongs to the
    sibling process and must not be used as the sender seam.
    """
    mgr = _manager()
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    rec = mgr.resolve_peer(peer_id)
    if rec is None:
        # R6: sanitised detail — never leak internal exception text to clients.
        raise HTTPException(status_code=404, detail="unknown peer")
    try:
        return mgr.send_message(peer_id, content, session_id=None)
    except ValueError:
        raise HTTPException(status_code=404, detail="peer unreachable") from None


@router.post("/peers/{peer_id}/policy")
def peer_policy(peer_id: str, body: dict, session_id: str | None = None) -> dict:
    """Set the inbound policy for a peer's session (G8 'Policy'; peer-policy
    equivalent). Policy is session-scoped (REM-210) and applies to THIS
    process's own session — the peer_id validates the target exists but the
    policy is set on the local single session (same as the peer-policy
    command)."""
    mgr = _manager()
    policy = (body.get("policy") or "").strip().lower()
    valid = {p.value for p in Policy}
    if policy not in valid:
        raise HTTPException(status_code=400, detail=f"invalid policy {policy!r}; expected one of {sorted(valid)}")
    rec = mgr.resolve_peer(peer_id)
    if rec is None:
        # R6: sanitised detail — never leak internal exception text to clients.
        raise HTTPException(status_code=404, detail="unknown peer")
    try:
        mgr.set_policy(policy, session_id=None)
    except ValueError:
        raise HTTPException(status_code=404, detail="peer unreachable") from None
    return {"ok": True, "peer_id": peer_id, "policy": policy}


# ---------------------------------------------------------------------------
# Live events (G6.7: WebSocket accelerates; polling is the fallback)
# ---------------------------------------------------------------------------


@router.websocket("/events")
async def events_ws(ws: WebSocket) -> None:
    if not _ws_upgrade_authorized(ws):
        await ws.close(code=4401)
        return
    mgr = _manager()
    sid = mgr.subscribe_events()
    await ws.accept()
    try:
        while True:
            events = mgr.drain_events(sid)
            import json

            # Always answer with a frame (events when present, else an empty
            # heartbeat) so the client's receive is never left hanging and
            # slow consumers are bounded by the broker queue (G6.7).
            await ws.send_text(json.dumps({"events": events}))
            try:
                await ws.receive_text()  # keepalive / client ping
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        mgr.unsubscribe_events(sid)
