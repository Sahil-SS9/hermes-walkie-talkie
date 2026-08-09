"""Human commands: /peers, /peer-name, /peer-policy, /peer-inbox and the
`hermes peer ...` CLI (HP-804..HP-808)."""

from __future__ import annotations

import json
import logging

from agent_peer.models import Policy

from .plugin import get_manager

logger = logging.getLogger("hermes_peer.commands")


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
    ctx.register_cli_command(
        "peer",
        help="Peer messaging: list, send, inbox, name, policy, doctor.",
        setup_fn=build_peer_cli_parser,
        handler_fn=None,
        description="Same-machine peer messaging between Hermes sessions.",
    )


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


def cmd_peers(_raw: str) -> str:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    lines = ["Live peers:"]
    for record in mgr.list_peers():  # discovery: all live peers, incl. local
        repo = record.git_branch or record.cwd
        lines.append(
            f"  {record.name}  ({record.peer_id[:8]}…)  "
            f"{record.surface}/{record.status}  {record.profile or '-'}  {repo}"
        )
    if len(lines) == 1:
        return "No live peers."
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


def run_peer_cli(args) -> int:
    """Dispatch `hermes peer <action>`; returns an exit code."""
    mgr = get_manager()
    if mgr is None:
        print("hermes-peer is not active in this process.")
        return 1
    action = getattr(args, "peer_action", None)

    if action == "list":
        print(cmd_peers(""))
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
    print("Usage: hermes peer {list|send|inbox|name|policy|doctor}")
    return 2


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
