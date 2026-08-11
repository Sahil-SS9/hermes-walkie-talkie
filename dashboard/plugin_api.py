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
                "cwd": record.cwd,
                "git_branch": record.git_branch,
            }
        )
    return {"peers": rows}


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
