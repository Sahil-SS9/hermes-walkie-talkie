"""Hermes agent tools: peer_list_agents, peer_send_message, peer_read_inbox (HP-801..HP-803).

Exactly three tools in v1, with stable JSON schemas and useful errors.
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


def peer_list_agents(args: dict) -> str:
    """Return reachable peers: id, name, profile, surface, cwd/repo, status."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    peers = []
    for record in mgr.list_peers():
        # Registry records are only listed when their socket is live: the
        # runtime registers every listed peer with a bound socket, and
        # stale entries (dead PID + failed handshake) are pruned by the
        # supervisor. A registry-only row without a local handle is never
        # reachable and therefore never listed here.
        if record.peer_id not in mgr._peer_handles:
            continue
        peers.append(
            {
                "peer_id": record.peer_id,
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
    """Resolve target to a peer record; (record, None) or (None, error)."""
    record = mgr.resolve_peer(target)
    if record is not None:
        return record, None
    # Name resolution: exact match; ambiguity is reported, never guessed.
    matches = [r for r in mgr.list_peers() if r.name == target]
    if not matches:
        return None, {"error": f"no reachable peer named or identified by {target!r}"}
    if len(matches) > 1:
        return None, {
            "error": f"ambiguous target {target!r}: {len(matches)} peers share this name; use an exact peer_id"
        }
    return matches[0], None


def peer_send_message(args: dict) -> str:
    """Send to an exact peer; await the transport receipt; return its state."""
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
    try:
        receipt = mgr.send_message(record.peer_id, message, reply_to=args.get("reply_to"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("peer_send_message failed: %s", exc)
        return json.dumps({"error": f"send failed: {exc}"})
    return json.dumps(receipt)


def peer_read_inbox(args: dict) -> str:
    """List held/queued messages or apply release/refuse to one message."""
    mgr, err = _manager_or_error()
    if err:
        return json.dumps(err)
    action = (args.get("action") or "list").strip().lower()
    if action not in ("list", "release", "refuse"):
        return json.dumps({"error": f"unknown action {action!r}; expected list|release|refuse"})
    if action == "list":
        return json.dumps({"messages": mgr.read_inbox()})
    message_id = (args.get("message_id") or "").strip()
    if not message_id:
        return json.dumps({"error": "message_id is required for release/refuse"})
    if action == "release":
        ok = mgr.release_message(message_id)
        return json.dumps({"released": ok, "message_id": message_id} if ok else {"error": f"no held message {message_id}"})
    ok = mgr.refuse_message(message_id)
    return json.dumps({"refused": ok, "message_id": message_id} if ok else {"error": f"no held message {message_id}"})
