"""Hermes agent tools: peer_list_agents, peer_send_message, peer_read_inbox
plus the V1.1 request and group tools.

The V1 surface is peer_list_agents / peer_send_message / peer_read_inbox
(HP-801..HP-803). V1.1 adds the request tools (peer_request_create,
peer_request_status, peer_request_respond, peer_request_cancel) and the
group tools (peer_group_list, peer_group_manage, peer_broadcast) — ten
tools total, each with a stable JSON schema and useful errors.
Handlers are pure functions of ``(args)`` that resolve the process-global
manager; the manager is registered by ``hermes_peer.plugin.register``.
"""

from __future__ import annotations

import json
import logging

from .plugin import get_manager

logger = logging.getLogger("hermes_peer.tools")


def _manager_or_error() -> tuple:
    mgr = get_manager()
    if mgr is None:
        return None, {"error": "hermes-peer is not active in this process"}
    return mgr, None


def register_tools(ctx) -> None:
    """Register the three v1 tools on the plugin context."""
    ctx.register_tool(
        "peer_list_agents",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=peer_list_agents,
        description="List reachable peer agent sessions on this machine (same user).",
        emoji="🛰️",
    )
    ctx.register_tool(
        "peer_send_message",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Exact peer_id or an unambiguous peer name.",
                },
                "message": {"type": "string", "description": "Message text to send."},
                "reply_to": {"type": "string", "description": "Optional message_id being replied to."},
            },
            "required": ["target", "message"],
            "additionalProperties": False,
        },
        handler=peer_send_message,
        description="Send a peer message to one exact agent session and return the delivery receipt.",
        emoji="📨",
    )
    ctx.register_tool(
        "peer_read_inbox",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "release", "refuse"],
                    "description": "list (default), release a held message, or refuse it.",
                },
                "message_id": {
                    "type": "string",
                    "description": "Required for release/refuse.",
                },
            },
            "additionalProperties": False,
        },
        handler=peer_read_inbox,
        description="List held/queued peer messages, or release/refuse a held message.",
        emoji="📥",
    )
    ctx.register_tool(
        "peer_request_create",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "target_agent_id": {
                    "type": "string",
                    "description": "Stable agent_id of the recipient agent.",
                },
                "summary": {"type": "string", "description": "Short request summary."},
                "detail": {"type": "string", "description": "Optional longer detail."},
                "idempotency_key": {
                    "type": "string",
                    "description": "Optional; repeated key returns the original request.",
                },
            },
            "required": ["target_agent_id", "summary"],
            "additionalProperties": False,
        },
        handler=peer_request_create,
        description="Create and enqueue a structured request to one agent (conversational input only).",
        emoji="📋",
    )
    ctx.register_tool(
        "peer_request_status",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Request id to query."},
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
        handler=peer_request_status,
        description="Poll the state timeline of a structured request.",
        emoji="🔎",
    )
    ctx.register_tool(
        "peer_request_respond",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Request id."},
                "action": {
                    "type": "string",
                    "enum": ["accept", "progress", "complete", "fail", "refuse"],
                    "description": "Recipient action on the request.",
                },
                "detail": {"type": "string", "description": "Optional progress note."},
            },
            "required": ["request_id", "action"],
            "additionalProperties": False,
        },
        handler=peer_request_respond,
        description="Recipient: accept/progress/complete/fail/refuse a structured request.",
        emoji="✅",
    )
    ctx.register_tool(
        "peer_request_cancel",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Request id."},
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
        handler=peer_request_cancel,
        description="Advisory cancellation of a structured request (never interrupts tools).",
        emoji="⏹️",
    )
    ctx.register_tool(
        "peer_group_list",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=peer_group_list,
        description="List persistent peer groups with member counts.",
        emoji="👥",
    )
    ctx.register_tool(
        "peer_group_manage",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "add_member", "remove_member", "delete"],
                    "description": "Group operation.",
                },
                "name": {"type": "string", "description": "Group name (create)."},
                "group_id": {"type": "string", "description": "Group id (add/remove/delete)."},
                "member_agent_id": {
                    "type": "string",
                    "description": "Stable agent_id of the member (add/remove).",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        handler=peer_group_manage,
        description="Create a group, add/remove a member by stable agent_id, or delete a group.",
        emoji="⚙️",
    )
    ctx.register_tool(
        "peer_broadcast",
        toolset="hermes-peer",
        schema={
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "description": "Group id to broadcast to."},
                "message": {"type": "string", "description": "Message text."},
            },
            "required": ["group_id", "message"],
            "additionalProperties": False,
        },
        handler=peer_broadcast,
        description="Broadcast one message to every live member session of a group (partial results explicit).",
        emoji="📣",
    )


def peer_list_agents(args: dict, **kwargs) -> str:
    """Return LIVE peers discovered via the discovery service (F-01).

    Cross-process peers are probed through their recorded sockets and listed;
    the local connection map is never a filter.
    """
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    peers = []
    for record in mgr.list_peers():  # discovery: all live peers, incl. same-process
        peers.append(
            {
                "peer_id": record.peer_id,
                "agent_id": record.agent_id,
                "name": record.name,
                "profile": record.profile,
                "surface": record.surface,
                "status": record.status,
                "cwd": record.cwd,
                "git_repo_root": record.git_repo_root,
                "git_branch": record.git_branch,
            }
        )
    return json.dumps({"peers": peers})


def _resolve_target(mgr, target: str) -> tuple:
    """Resolve target to a live peer record; (record, None) or (None, error).

    Uses the discovery service's fail-closed resolver: exact peer ID, exact
    live session ID, ``name~shortID``, or a unique bare name. Collisions
    return every candidate and never pick the first.
    """
    return mgr.resolve_target(target)


def peer_send_message(args: dict, **kwargs) -> str:
    """Send to an exact peer; await the transport receipt; return its state.

    The invoking ``session_id`` comes from Hermes dispatch kwargs (REM-211).
    """
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    target = (args.get("target") or "").strip()
    message = args.get("message") or ""
    if not target or not message:
        return json.dumps({"error": "target and message are required"})
    record, err = _resolve_target(mgr, target)
    if err:
        return json.dumps(err)
    session_id = kwargs.get("session_id")
    try:
        receipt = mgr.send_message(record.peer_id, message, reply_to=args.get("reply_to"), session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("peer_send_message failed: %s", exc)
        return json.dumps({"error": f"send failed: {exc}"})
    return json.dumps(receipt)


def peer_read_inbox(args: dict, **kwargs) -> str:
    """List held/queued messages or apply release/refuse to one message.

    The invoking ``session_id`` comes from Hermes dispatch kwargs (REM-211).
    """
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    session_id = kwargs.get("session_id")
    action = (args.get("action") or "list").strip().lower()
    if action not in ("list", "release", "refuse"):
        return json.dumps({"error": f"unknown action {action!r}; expected list|release|refuse"})
    if action == "list":
        try:
            return json.dumps({"messages": mgr.read_inbox(session_id=session_id)})
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
    message_id = (args.get("message_id") or "").strip()
    if not message_id:
        return json.dumps({"error": "message_id is required for release/refuse"})
    if action == "release":
        ok = mgr.release_message(message_id, session_id=session_id)
        return json.dumps({"released": ok, "message_id": message_id} if ok else {"error": f"no held message {message_id}"})
    ok = mgr.refuse_message(message_id, session_id=session_id)
    return json.dumps({"refused": ok, "message_id": message_id} if ok else {"error": f"no held message {message_id}"})


def peer_request_create(args: dict, **kwargs) -> str:
    """Create + enqueue a structured request to one agent (P5, G4).

    The request is conversational input only — it cannot approve tools,
    invoke slash commands or bypass policy (G4.9).
    """
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    target_agent_id = (args.get("target_agent_id") or "").strip()
    summary = (args.get("summary") or "").strip()
    if not target_agent_id or not summary:
        return json.dumps({"error": "target_agent_id and summary are required"})
    session_id = kwargs.get("session_id")
    try:
        result = mgr.create_request(
            target_agent_id,
            summary,
            payload={"detail": args.get("detail")} if args.get("detail") else None,
            idempotency_key=args.get("idempotency_key") or "",
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("peer_request_create failed: %s", exc)
        return json.dumps({"error": f"request failed: {exc}"})
    return json.dumps(result)


def peer_request_status(args: dict, **kwargs) -> str:
    """Poll the state timeline of a structured request (G4.10)."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    request_id = (args.get("request_id") or "").strip()
    if not request_id:
        return json.dumps({"error": "request_id is required"})
    session_id = kwargs.get("session_id")
    try:
        return json.dumps(mgr.request_status(request_id, session_id=session_id))
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


def peer_request_respond(args: dict, **kwargs) -> str:
    """Recipient action on a structured request (G4.5)."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    request_id = (args.get("request_id") or "").strip()
    action = (args.get("action") or "").strip().lower()
    if not request_id or action not in ("accept", "progress", "complete", "fail", "refuse"):
        return json.dumps({"error": "request_id and action (accept|progress|complete|fail|refuse) are required"})
    session_id = kwargs.get("session_id")
    try:
        return json.dumps(
            mgr.request_respond(request_id, action, detail=args.get("detail") or "", session_id=session_id)
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


def peer_request_cancel(args: dict, **kwargs) -> str:
    """Advisory cancellation of a structured request (G4.6)."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    request_id = (args.get("request_id") or "").strip()
    if not request_id:
        return json.dumps({"error": "request_id is required"})
    session_id = kwargs.get("session_id")
    try:
        return json.dumps(mgr.request_cancel(request_id, session_id=session_id))
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


def peer_group_list(args: dict, **kwargs) -> str:
    """List persistent groups with member counts (P7.2, G3)."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    try:
        return json.dumps({"groups": mgr.group_list()})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


def peer_group_manage(args: dict, **kwargs) -> str:
    """Create/add-member/remove-member/delete a persistent group (P7.2)."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    action = (args.get("action") or "").strip()
    session_id = kwargs.get("session_id")
    try:
        if action == "create":
            name = (args.get("name") or "").strip()
            if not name:
                return json.dumps({"error": "name is required for create"})
            return json.dumps(mgr.group_create(name, session_id=session_id))
        if action in ("add_member", "remove_member"):
            group_id = (args.get("group_id") or "").strip()
            member = (args.get("member_agent_id") or "").strip()
            if not group_id or not member:
                return json.dumps({"error": "group_id and member_agent_id are required"})
            if action == "add_member":
                return json.dumps(mgr.group_add_member(group_id, member, session_id=session_id))
            return json.dumps(mgr.group_remove_member(group_id, member, session_id=session_id))
        if action == "delete":
            group_id = (args.get("group_id") or "").strip()
            if not group_id:
                return json.dumps({"error": "group_id is required for delete"})
            return json.dumps(mgr.group_delete(group_id, session_id=session_id))
        return json.dumps({"error": f"unknown group action {action!r}"})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


def peer_broadcast(args: dict, **kwargs) -> str:
    """Broadcast to every live member session of a group (P7.2, G3.5/G3.6)."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    group_id = (args.get("group_id") or "").strip()
    message = (args.get("message") or "").strip()
    if not group_id or not message:
        return json.dumps({"error": "group_id and message are required"})
    session_id = kwargs.get("session_id")
    try:
        return json.dumps(mgr.broadcast_send(group_id, message, session_id=session_id))
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
