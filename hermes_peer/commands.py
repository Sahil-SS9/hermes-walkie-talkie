"""Human commands: /peers, /peer-name, /peer-policy, /peer-inbox and the
`hermes peer ...` CLI (HP-804..HP-808)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agent_peer.models import Policy

from .plugin import get_manager

logger = logging.getLogger("hermes_peer.commands")

# S9: status glyph map mirroring the dashboard DOT_CLASS_MAP — one source for
# the ●/○/× per-status markers in `hermes peer ls`.
STATUS_GLYPH = {
    "working": "●",
    "held": "●",
    "closing": "●",
    "idle": "○",
}


def register_commands(ctx) -> None:
    """Register slash commands and the `hermes peer` CLI subcommand."""
    ctx.register_command(
        "peers",
        handler=cmd_peers,
        description="List live peer agent sessions.",
    )
    ctx.register_command(
        "peer-name",
        handler=cmd_peer_name,
        description="Set this session's peer alias.",
        args_hint="<name>",
    )
    ctx.register_command(
        "peer-policy",
        handler=cmd_peer_policy,
        description="Set the inbound policy: accept|hold|refuse.",
        args_hint="<accept|hold|refuse>",
    )
    ctx.register_command(
        "peer-inbox",
        handler=cmd_peer_inbox,
        description="List held peer messages; release/refuse with the agent tools.",
        args_hint="",
    )
    ctx.register_command(
        "peer-groups",
        handler=cmd_peer_groups,
        description="List persistent peer groups.",
        args_hint="",
    )
    ctx.register_command(
        "peer-group",
        handler=cmd_peer_group,
        description="Manage a group: create|add|remove|delete.",
        args_hint="create <name> | add <group_id> <agent_id> | remove <group_id> <agent_id> | delete <group_id>",
    )
    ctx.register_command(
        "peer-broadcast",
        handler=cmd_peer_broadcast,
        description="Broadcast a message to every live member of a group.",
        args_hint="<group_id> <message>",
    )
    ctx.register_command(
        "peer-request",
        handler=cmd_peer_request,
        description="Structured request: create|status|respond|cancel.",
        args_hint="create <agent_id> <summary> | status <request_id> | respond <request_id> <action> | cancel <request_id>",
    )
    ctx.register_cli_command(
        "peer",
        help="Peer messaging: list, send, inbox, name, policy, doctor, groups, broadcast, request.",
        setup_fn=build_peer_cli_parser,
        handler_fn=None,
        description="Same-machine peer messaging between Hermes sessions.",
    )


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


def cmd_peers(_raw: str) -> str | dict:
    """List live interactive sessions.

    Returns a structured interactive result (dict with ``interactive``) so
    the host can render an arrow-key picker. The host falls back to printing
    the plain string for non-interactive surfaces.
    """
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    summary = mgr.summary()
    you_id = summary["you_peer_id"]
    live = summary.get("live_count", 0)
    rows = [
        row for row in summary["peers"]
        if row["surface"] != "gateway" and not row["offline"]
    ]
    items = []
    for row in rows:
        marker = "▸" if row["peer_id"] == you_id else "○"
        you = " (you)" if row["peer_id"] == you_id else ""
        status = f"{STATUS_GLYPH.get(row['status_label'], '×')}{row['status_label']}"
        activity = row["current_activity"] or "—"
        items.append({
            "label": f"{marker} {row['name']}{you}  {row['surface']}  {status}  "
                     f"{activity}  {row['profile'] or '-'}",
            "detail": (
                f"Peer: {row['name']}{you}\n"
                f"  id: {row['peer_id']}\n"
                f"  surface: {row['surface']}\n"
                f"  status: {status}\n"
                f"  activity: {activity}\n"
                f"  profile: {row['profile'] or 'default'}\n"
                f"  cwd: {row['cwd']}\n"
                f"  branch: {row['git_branch'] or '—'}\n"
                f"  last seen: {row['last_seen'] or '—'}"
            ),
        })
    if not rows:
        return {"interactive": {
            "title": "Peers",
            "items": [],
            "empty": "No live interactive sessions.",
        }}
    return {"interactive": {
        "title": f"Peers · {live} live · {summary['active_count']} working · "
                 f"{summary['idle_count']} idle",
        "items": items,
    }}


def _cmd_peers_plain() -> str:
    """Plain-text fallback for non-interactive surfaces (kept for tests)."""
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    summary = mgr.summary()
    you_id = summary["you_peer_id"]
    live = summary.get("live_count", 0)
    rows = [
        row for row in summary["peers"]
        if row["surface"] != "gateway" and not row["offline"]
    ]
    lines = [
        f"Live sessions · {live}   ● {summary['active_count']} working   "
        f"○ {summary['idle_count']} idle   × {summary['offline_count']} offline   "
        f"[live {summary['last_updated'] or '—'}]"
    ]
    for row in rows:
        marker = "▸" if row["peer_id"] == you_id else "○"
        you = " (you)" if row["peer_id"] == you_id else ""
        status = f"{STATUS_GLYPH.get(row['status_label'], '×')}{row['status_label']}"
        repo = row["git_branch"] or row["cwd"]
        activity = row["current_activity"] or "—"
        lines.append(
            f"  {marker} {row['name']}{you}  {row['surface']}  {status}  "
            f"{activity}  {row['profile'] or '-'}  {repo}"
        )
    if not rows:
        return "No live interactive sessions."
    return "\n".join(lines)


def cmd_peer_name(raw: str, **kwargs) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    name = (raw or "").strip()
    if not name:
        return "Usage: /peer-name <name>"
    session_id = kwargs.get("session_id")
    try:
        if not mgr._peers:
            return "No active peer session to name."
        mgr.set_alias(name, session_id=session_id)
    except ValueError as exc:
        return f"Invalid name: {exc}"
    return f"Peer renamed to '{name}'."


def cmd_peer_policy(raw: str, **kwargs) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    policy = (raw or "").strip().lower()
    if policy not in {p.value for p in Policy}:
        return f"Invalid policy {policy!r}; expected one of {sorted(p.value for p in Policy)}"
    session_id = kwargs.get("session_id")
    try:
        mgr.set_policy(policy, session_id=session_id)
    except ValueError as exc:
        return f"Invalid policy: {exc}"
    return f"Inbound policy set to '{policy}'."


def cmd_peer_inbox(_raw: str, **kwargs) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    session_id = kwargs.get("session_id")
    try:
        messages = mgr.read_inbox(session_id=session_id)
    except ValueError as exc:
        return f"Inbox error: {exc}"
    if not messages:
        return "Inbox is empty."
    lines = [f"Held/queued messages ({len(messages)}):"]
    for row in messages:
        lines.append(
            f"  {row['message_id'][:8]}… [{row['state']}] from {row['sender_peer_id'][:8]}…: "
            f"{row['content'][:80]}"
        )
    lines.append("Release or refuse via the peer_read_inbox tool.")
    return "\n".join(lines)


def cmd_peer_groups(_raw: str, **kwargs) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    try:
        groups = mgr.group_list()
    except ValueError as exc:
        return f"Group error: {exc}"
    if not groups:
        return "No groups."
    lines = [f"Groups ({len(groups)}):"]
    for g in groups:
        lines.append(f"  {g['name']}  ({g['group_id'][:8]}…)  {g['members']} members")
    return "\n".join(lines)


def cmd_peer_group(raw: str, **kwargs) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    parts = (raw or "").split()
    if not parts:
        return "Usage: /peer-group create <name> | add <group_id> <agent_id> | remove <group_id> <agent_id> | delete <group_id>"
    action = parts[0].lower()
    session_id = kwargs.get("session_id")
    try:
        if action == "create" and len(parts) >= 2:
            result = mgr.group_create(" ".join(parts[1:]), session_id=session_id)
            return f"Created group '{result['name']}' ({result['group_id']})."
        if action == "add" and len(parts) >= 3:
            mgr.group_add_member(parts[1], parts[2], session_id=session_id)
            return f"Added {parts[2]} to {parts[1]}."
        if action == "remove" and len(parts) >= 3:
            mgr.group_remove_member(parts[1], parts[2], session_id=session_id)
            return f"Removed {parts[2]} from {parts[1]}."
        if action == "delete" and len(parts) >= 2:
            mgr.group_delete(parts[1], session_id=session_id)
            return f"Deleted group {parts[1]}."
    except ValueError as exc:
        return f"Group error: {exc}"
    return "Usage: /peer-group create <name> | add <group_id> <agent_id> | remove <group_id> <agent_id> | delete <group_id>"


def cmd_peer_broadcast(raw: str, **kwargs) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    parts = (raw or "").split(maxsplit=1)
    if len(parts) < 2:
        return "Usage: /peer-broadcast <group_id> <message>"
    session_id = kwargs.get("session_id")
    try:
        result = mgr.broadcast_send(parts[0], parts[1], session_id=session_id)
        summary = result["summary"]
        return (
            f"Broadcast {summary['broadcast_id'][:8]}…: "
            f"{summary['queued']} queued, {summary['skipped']} skipped, "
            f"{summary['unreachable']} unreachable"
        )
    except ValueError as exc:
        return f"Broadcast error: {exc}"


def cmd_peer_request(raw: str, **kwargs) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    parts = (raw or "").split()
    if not parts:
        return "Usage: /peer-request create <agent_id> <summary> | status <request_id> | respond <request_id> <action> | cancel <request_id>"
    action = parts[0].lower()
    session_id = kwargs.get("session_id")
    try:
        if action == "create" and len(parts) >= 3:
            result = mgr.create_request(parts[1], " ".join(parts[2:]), session_id=session_id)
            return f"Request {result['request_id'][:8]}… created (delivered={result['delivered']})."
        if action == "status" and len(parts) >= 2:
            status = mgr.request_status(parts[1], session_id=session_id)
            return f"Request {status['request_id'][:8]}… [{status['state']}] {status['summary']}"
        if action == "respond" and len(parts) >= 3:
            result = mgr.request_respond(parts[1], parts[2], session_id=session_id)
            return f"Request {result['request_id'][:8]}… -> {result['state']}"
        if action == "cancel" and len(parts) >= 2:
            result = mgr.request_cancel(parts[1], session_id=session_id)
            return f"Request {result['request_id'][:8]}… -> {result['state']}"
    except ValueError as exc:
        return f"Request error: {exc}"
    return "Usage: /peer-request create <agent_id> <summary> | status <request_id> | respond <request_id> <action> | cancel <request_id>"


# ---------------------------------------------------------------------------
# `hermes peer ...` CLI
# ---------------------------------------------------------------------------


def build_peer_cli_parser(subparsers) -> None:
    """Add the peer subcommands (list, send, inbox, name, policy, doctor)."""
    p = subparsers.add_parser("peer", help="Peer messaging between Hermes sessions.")
    peer_sub = p.add_subparsers(dest="peer_action", required=True)

    peer_sub.add_parser("list", help="List live peers.")
    peer_sub.add_parser("doctor", help="Diagnose runtime dir, seam and registry.")

    send = peer_sub.add_parser("send", help="Send a message to a peer.")
    send.add_argument("target", help="Exact peer_id or unambiguous name.")
    send.add_argument("message", help="Message text.")
    send.add_argument("--reply-to", default=None, help="Message id being replied to.")

    inbox = peer_sub.add_parser("inbox", help="List held/queued messages.")
    inbox.add_argument("--action", choices=["list", "release", "refuse"], default="list")
    inbox.add_argument("--message-id", default=None)

    name = peer_sub.add_parser("name", help="Set this session's alias.")
    name.add_argument("name")

    policy = peer_sub.add_parser("policy", help="Set the inbound policy.")
    policy.add_argument("policy", choices=[p.value for p in Policy])

    peer_sub.add_parser("groups", help="List persistent groups.")
    group = peer_sub.add_parser("group", help="Manage a group.")
    group.add_argument("action", choices=["create", "add", "remove", "delete"])
    group.add_argument("arg1", help="Group name (create) or group_id (add/remove/delete).")
    group.add_argument("arg2", nargs="?", default=None, help="Member agent_id (add/remove).")

    broadcast = peer_sub.add_parser("broadcast", help="Broadcast to every live member of a group.")
    broadcast.add_argument("group_id")
    broadcast.add_argument("message")

    request = peer_sub.add_parser("request", help="Structured request lifecycle.")
    request.add_argument("action", choices=["create", "status", "respond", "cancel"])
    request.add_argument("arg1", help="Agent_id (create) or request_id (status/respond/cancel).")
    request.add_argument("arg2", nargs="?", default=None, help="Summary (create) or action (respond).")
    request.add_argument("arg3", nargs="?", default=None, help="Respond detail.")

    desktop = peer_sub.add_parser("desktop", help="Install/status/remove the Hermes Desktop peer plugin.")
    desktop.add_argument("action", choices=["install", "status", "remove"], default="status", nargs="?")
    desktop.add_argument("--home", default=None, help="HERMES_HOME to install into (default: current).")


def run_peer_cli(args) -> int:
    """Dispatch `hermes peer <action>`; returns an exit code."""
    mgr = get_manager()
    if mgr is None:
        print("hermes-peer is not active in this process.")
        return 1
    action = getattr(args, "peer_action", None)

    if action == "list":
        print(_cmd_peers_plain())
        return 0
    if action == "doctor":
        report = mgr.doctor()
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    if action == "send":
        result = peer_send_cli(mgr, args)
        print(result)
        return 0
    if action == "inbox":
        if args.action not in ("list", "release", "refuse"):
            print(f"Unknown inbox action {args.action!r}; expected list|release|refuse")
            return 2
        if args.action == "list":
            print(cmd_peer_inbox(""))
            return 0
        if args.action == "release":
            ok = mgr.release_message(args.message_id) if args.message_id else False
            print("released" if ok else "no held message with that id")
            return 0 if ok else 1
        ok = mgr.refuse_message(args.message_id) if args.message_id else False
        print("refused" if ok else "no held message with that id")
        return 0 if ok else 1
    if action == "name":
        print(cmd_peer_name(args.name))
        return 0
    if action == "policy":
        print(cmd_peer_policy(args.policy))
        return 0
    if action == "groups":
        print(cmd_peer_groups(""))
        return 0
    if action == "group":
        raw = " ".join(
            part for part in (args.action, args.arg1, args.arg2 or "") if part
        )
        print(cmd_peer_group(raw))
        return 0
    if action == "broadcast":
        print(cmd_peer_broadcast(f"{args.group_id} {args.message}"))
        return 0
    if action == "request":
        raw = " ".join(part for part in (args.action, args.arg1, args.arg2 or "", args.arg3 or "") if part)
        print(cmd_peer_request(raw))
        return 0
    if action == "desktop":
        return run_desktop_cli(mgr, args)
    print("Usage: hermes peer {list|send|inbox|name|policy|doctor|groups|group|broadcast|request|desktop}")
    return 2


def run_desktop_cli(mgr, args) -> int:
    """`hermes peer desktop install|status|remove` (P7.7).

    Explicitly installs the compiled Desktop plugin into a supplied or
    disposable HERMES_HOME; NEVER auto-installs (G6.9).
    """
    from .desktop_install import (
        desktop_plugin_status,
        install_desktop_plugin,
        remove_desktop_plugin,
    )

    home = Path(args.home) if args.home else None
    try:
        if args.action == "install":
            target = install_desktop_plugin(home=home)
            print(f"Installed Hermes Peer Desktop plugin at {target}")
            return 0
        if args.action == "remove":
            removed = remove_desktop_plugin(home=home)
            print("Removed Desktop plugin." if removed else "Desktop plugin not present.")
            return 0 if removed else 1
        status = desktop_plugin_status(home=home)
        print(json.dumps(status, indent=2))
        return 0 if status.get("installed") else 1
    except (ValueError, OSError) as exc:
        print(f"Desktop plugin error: {exc}")
        return 1


def peer_send_cli(mgr, args) -> str:
    from .tools import _resolve_target

    record, err = _resolve_target(mgr, args.target)
    if err:
        return err["error"]
    try:
        receipt = mgr.send_message(record.peer_id, args.message, reply_to=args.reply_to)
    except Exception as exc:  # noqa: BLE001
        return f"send failed: {exc}"
    return f"{receipt['state']} (message {receipt['message_id']})"
