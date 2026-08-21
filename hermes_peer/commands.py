"""Human commands: /peers, /peer-name, /peer-policy, /peer-inbox and the
`hermes peer ...` CLI (HP-804..HP-808)."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
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


def _usage_log(command: str, raw_args: str = "", *, session_id: str | None = None, outcome: str = "ok") -> None:
    """Append one command-usage record (JSONL) to the peer state root.

    Every slash-command invocation is captured here so there is an audit
    trail of which peer commands ran, from which session, and with what
    outcome. Path: <state_root>/command-usage.jsonl. Best-effort — a
    logging failure never breaks the command.
    """
    try:
        mgr = get_manager()
        if mgr is None:
            return
        root = getattr(mgr, "_paths", None)
        if root is None:
            return
        log_path = Path(root.root) / "command-usage.jsonl"
        rec = {
            "ts": datetime.now(UTC).isoformat(),
            "epoch": time.time(),
            "command": command,
            "args": (raw_args or "")[:200],
            "session_id": session_id,
            "outcome": outcome,
        }
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001 — never break the command for logging
        logger.debug("command-usage log failed", exc_info=True)


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


def cmd_peers(_raw: str, **kwargs) -> str | dict:
    """List live interactive sessions with nested drill-down actions.

    Returns a structured interactive result (dict with ``interactive``) so
    the host's recursive menu engine can drive: pick a peer → action picker
    (Send / Inbox / Policy / Rename / Refresh) → each action may prompt or
    open a nested spec. Esc pops one level. Non-interactive surfaces get the
    plain string fallback.
    """
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peers", _raw, session_id=kwargs.get("session_id"))
    # The invoking session — threaded into every mutating action so the
    # manager binds to THIS session (multi-session hosts raise otherwise).
    session_id = kwargs.get("session_id") or None
    summary = mgr.summary()
    you_id = summary["you_peer_id"]
    live = summary.get("live_count", 0)
    rows = [
        row for row in summary["peers"]
        if row["surface"] != "gateway" and not row["offline"]
    ]
    items = []
    for row in rows:
        peer_id = row["peer_id"]
        marker = "▸" if peer_id == you_id else "○"
        you = " (you)" if peer_id == you_id else ""
        status = f"{STATUS_GLYPH.get(row['status_label'], '×')}{row['status_label']}"
        activity = row["current_activity"] or "—"

        # Per-peer actions — fully declarative. Each handler takes
        # (peer_id, text=None) and returns a string (printed) or a nested
        # interactive spec (host recurses). The host owns ALL I/O: free-text
        # actions set ``prompt`` and the host calls _prompt_text_input, then
        # invokes the handler with the collected text. Plugin code never
        # calls input().
        def _act_send(value, text=None, _peer=row, _sid=session_id):
            if not text or not text.strip():
                return "Cancelled."
            try:
                rec = mgr.send_message(_peer["peer_id"], text, session_id=_sid)
                return f"Sent: {rec['state']}"
            except ValueError as exc:
                return f"Send failed: {exc}"

        def _act_inbox(value, text=None, _peer=row, _sid=session_id):
            try:
                messages = mgr.read_inbox(session_id=_sid)
            except ValueError as exc:
                return f"Inbox error: {exc}"
            if not messages:
                return f"{_peer['name']} inbox is empty."
            lines = [f"{_peer['name']} inbox ({len(messages)}):"]
            for m in messages:
                lines.append(
                    f"  {m['message_id'][:8]}… [{m['state']}] {m['content'][:60]}"
                )
            return "\n".join(lines)

        def _act_policy(value, text=None, _sid=session_id):
            # text is the chosen policy name (host collects via a nested picker)
            policy = (text or "").strip().lower()
            if policy not in ("accept", "hold", "refuse"):
                return f"Invalid policy '{policy}'."
            try:
                mgr.set_policy(policy, session_id=_sid)
                return f"Policy set to {policy}."
            except ValueError as exc:
                return f"Policy failed: {exc}"

        def _act_rename(value, text=None, _peer=row, _sid=session_id):
            name = (text or "").strip()
            if not name:
                return "Cancelled."
            try:
                mgr.set_alias(name, session_id=_sid)
                return f"Renamed to '{name}'."
            except ValueError as exc:
                return f"Rename failed: {exc}"

        # Policy sub-menu: nested picker so the user chooses accept/hold/refuse
        # with arrow keys instead of typing. NOTE: policy is session-scoped in
        # this codebase — this sets the INVOKING session's inbound policy, not
        # the selected peer's. The label/title say so to avoid implying a
        # per-peer policy edit that doesn't exist.
        _policy_menu = {
            "interactive": {
                "title": "Set MY inbound policy",
                "items": [
                    {"label": "accept  (auto-accept all inbound)", "value": "accept"},
                    {"label": "hold  (queue for review)", "value": "hold"},
                    {"label": "refuse  (reject all inbound)", "value": "refuse"},
                ],
                "actions": [
                    {"key": "q", "label": "Back", "handler": lambda v=None, t=None: None},
                ],
            }
        }

        items.append({
            "label": f"{marker} {row['name']}{you}  {row['surface']}  {status}  "
                     f"{activity}  {row['profile'] or '-'}",
            "value": peer_id,
            "detail": (
                f"Peer: {row['name']}{you}\n"
                f"  id: {peer_id}\n"
                f"  surface: {row['surface']}\n"
                f"  status: {status}\n"
                f"  activity: {activity}\n"
                f"  profile: {row['profile'] or 'default'}\n"
                f"  cwd: {row['cwd']}\n"
                f"  branch: {row['git_branch'] or '—'}\n"
                f"  last seen: {row['last_seen'] or '—'}"
            ),
            "actions": [
                {"key": "s", "label": "Send message", "handler": _act_send,
                 "prompt": f"Message to {row['name']}:"},
                {"key": "i", "label": "Inbox", "handler": _act_inbox},
                {"key": "p", "label": "Set MY inbound policy", "handler": _act_policy,
                 "children": _policy_menu},
                {"key": "r", "label": "Rename", "handler": _act_rename,
                 "prompt": f"New name for {row['name']}:"},
            ],
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
        "actions": [
            {"key": "q", "label": "Quit", "handler": lambda _v=None: None},
        ],
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


def cmd_peer_name(raw: str, **kwargs) -> str | dict:
    """Set this session's peer alias — guided prompt when called bare."""
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peer-name", raw, session_id=kwargs.get("session_id"))
    name = (raw or "").strip()
    if name:
        # Direct form still works: /peer-name <name>
        try:
            if not mgr._peers:
                return "No active peer session to name."
            mgr.set_alias(name, session_id=kwargs.get("session_id"))
        except ValueError as exc:
            return f"Invalid name: {exc}"
        return f"Peer renamed to '{name}'."
    # Guided: return a prompt spec; the host collects the name and re-runs.
    return {"interactive": {
        "title": "Rename this session",
        "items": [],
        "actions": [
            {"key": "n", "label": "Enter new name",
             "handler": _bind_sid(_rename_handler, kwargs.get("session_id")),
             "prompt": "New name for this session:"},
        ],
        "empty": "Choose an action below.",
    }}


def _bind_sid(handler, session_id):
    """Wrap a (value, text=None) handler so it receives the invoking session.

    Guided-flow handlers are module-level and cannot capture the ``session_id``
    kwarg the host passes to the ``cmd_*`` entry point. The spec builders wrap
    them here so every mutating call binds to THIS session (multi-session hosts
    raise ValueError otherwise).
    """

    def _wrapped(value=None, text=None, _h=handler, _sid=session_id):
        return _h(value, text, session_id=_sid)

    return _wrapped


def _rename_handler(_value=None, text=None, session_id=None):
    mgr = get_manager()
    name = (text or "").strip()
    if not name:
        return "Cancelled."
    try:
        if not mgr._peers:
            return "No active peer session to name."
        mgr.set_alias(name, session_id=session_id)
    except ValueError as exc:
        return f"Invalid name: {exc}"
    return f"Peer renamed to '{name}'."


def cmd_peer_policy(raw: str, **kwargs) -> str | dict:
    """Set the inbound policy — guided menu when called bare."""
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peer-policy", raw, session_id=kwargs.get("session_id"))
    policy = (raw or "").strip().lower()
    if policy:
        if policy not in {p.value for p in Policy}:
            return f"Invalid policy {policy!r}; expected one of {sorted(p.value for p in Policy)}"
        try:
            mgr.set_policy(policy, session_id=kwargs.get("session_id"))
        except ValueError as exc:
            return f"Invalid policy: {exc}"
        return f"Inbound policy set to '{policy}'."
    # Guided: arrow-key menu of accept/hold/refuse.
    return {"interactive": {
        "title": "Set inbound policy",
        "items": [
            {"label": "accept  — auto-accept all inbound", "value": "accept",
             "handler": _bind_sid(_policy_handler, kwargs.get("session_id"))},
            {"label": "hold  — queue for review", "value": "hold",
             "handler": _bind_sid(_policy_handler, kwargs.get("session_id"))},
            {"label": "refuse  — reject all inbound", "value": "refuse",
             "handler": _bind_sid(_policy_handler, kwargs.get("session_id"))},
        ],
        "empty": "Choose a policy.",
    }}


def _policy_handler(value, text=None, session_id=None):
    policy = (text or value or "").strip().lower()
    mgr = get_manager()
    try:
        mgr.set_policy(policy, session_id=session_id)
    except ValueError as exc:
        return f"Invalid policy: {exc}"
    return f"Inbound policy set to '{policy}'."


def cmd_peer_inbox(_raw: str, **kwargs) -> str | dict:
    """List held/queued messages — selectable, with release/refuse actions."""
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peer-inbox", _raw, session_id=kwargs.get("session_id"))
    session_id = kwargs.get("session_id")
    try:
        messages = mgr.read_inbox(session_id=session_id)
    except ValueError as exc:
        return f"Inbox error: {exc}"
    if not messages:
        return "Inbox is empty."
    items = []
    for m in messages:
        mid = m["message_id"]

        def _release(value, text=None, _mid=mid):
            try:
                ok = mgr.release_message(_mid, session_id=session_id)
                return f"Released {_mid[:8]}…: {ok}"
            except ValueError as exc:
                return f"Release failed: {exc}"

        def _refuse(value, text=None, _mid=mid):
            try:
                ok = mgr.refuse_message(_mid, session_id=session_id)
                return f"Refused {_mid[:8]}…: {ok}"
            except ValueError as exc:
                return f"Refuse failed: {exc}"

        items.append({
            "label": f"{m['message_id'][:8]}… [{m['state']}] from "
                     f"{m['sender_peer_id'][:8]}…: {m['content'][:48]}",
            "value": mid,
            "detail": (
                f"From: {m['sender_peer_id']}\n"
                f"State: {m['state']}\n"
                f"{m['content']}"
            ),
            "actions": [
                {"key": "r", "label": "Release", "handler": _release},
                {"key": "x", "label": "Refuse", "handler": _refuse},
            ],
        })
    return {"interactive": {
        "title": f"Inbox ({len(messages)})",
        "items": items,
        "actions": [
            {"key": "q", "label": "Close", "handler": lambda v=None, t=None: None},
        ],
    }}


def cmd_peer_groups(_raw: str, **kwargs) -> str | dict:
    """List persistent peer groups — drill into a group for members/actions."""
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peer-groups", _raw, session_id=kwargs.get("session_id"))
    sid = kwargs.get("session_id") or None
    try:
        groups = mgr.group_list()
    except ValueError as exc:
        return f"Group error: {exc}"
    if not groups:
        return {"interactive": {
            "title": "Groups",
            "items": [],
            "actions": [
                {"key": "c", "label": "Create group",
                 "handler": _bind_sid(_group_create_handler, sid),
                 "prompt": "New group name:"},
            ],
            "empty": "No groups yet.",
        }}
    items = []
    for g in groups:
        gid = g["group_id"]

        def _members(value, text=None, _gid=gid, _gname=g["name"]):
            try:
                mem = mgr.group_members_list(_gid)
            except ValueError as exc:
                return f"Members error: {exc}"
            if not mem:
                return f"Group {_gname}: no members."
            return "\n".join(f"  {m['agent_id']} ({m['peer_id'][:8]}…)" for m in mem)

        items.append({
            "label": f"{g['name']}  ({g['group_id'][:8]}…)  {g['members']} members",
            "value": gid,
            "detail": f"Group: {g['name']}\nid: {gid}\nmembers: {g['members']}",
            "actions": [
                {"key": "m", "label": "List members", "handler": _members},
                {"key": "a", "label": "Add member",
                 "handler": _bind_sid(_group_add_handler, sid),
                 "prompt": f"Agent id to add to {g['name']}:"},
                {"key": "d", "label": "Delete group",
                 "handler": _bind_sid(_group_delete_handler, sid)},
            ],
        })
    return {"interactive": {
        "title": f"Groups ({len(groups)})",
        "items": items,
        "actions": [
            {"key": "c", "label": "Create group",
             "handler": _bind_sid(_group_create_handler, sid),
             "prompt": "New group name:"},
            {"key": "q", "label": "Close", "handler": lambda v=None, t=None: None},
        ],
    }}


def _group_create_handler(_value=None, text=None, session_id=None):
    name = (text or "").strip()
    if not name:
        return "Cancelled."
    mgr = get_manager()
    try:
        res = mgr.group_create(name, session_id=session_id)
        return f"Created group '{res['name']}' ({res['group_id'][:8]}…)."
    except ValueError as exc:
        return f"Create failed: {exc}"


def _group_add_handler(value, text=None, session_id=None):
    agent = (text or "").strip()
    if not agent:
        return "Cancelled."
    mgr = get_manager()
    try:
        mgr.group_add_member(value, agent, session_id=session_id)
        return f"Added {agent} to group."
    except ValueError as exc:
        return f"Add failed: {exc}"


def _group_delete_handler(value, text=None, session_id=None):
    mgr = get_manager()
    try:
        mgr.group_delete(value, session_id=session_id)
        return f"Deleted group {value[:8]}…."
    except ValueError as exc:
        return f"Delete failed: {exc}"


def cmd_peer_group(raw: str, **kwargs) -> str | dict:
    """Manage a group: create|add|remove|delete (guided when called bare)."""
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peer-group", raw, session_id=kwargs.get("session_id"))
    parts = (raw or "").split()
    if not parts:
        # Guided: list actions.
        return {"interactive": {
            "title": "Group management",
            "items": [
                {"label": "Create group", "value": "create",
                 "handler": _bind_sid(_group_create_handler, kwargs.get("session_id")),
                 "prompt": "New group name:"},
            ],
            "empty": "Choose an action.",
        }}
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


def cmd_peer_broadcast(raw: str, **kwargs) -> str | dict:
    """Broadcast a message to a group — guided: choose group → message → confirm."""
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peer-broadcast", raw, session_id=kwargs.get("session_id"))
    parts = (raw or "").split(maxsplit=1)
    if len(parts) >= 2:
        # Direct form: /peer-broadcast <group_id> <message>
        return _do_broadcast(parts[0], parts[1], kwargs.get("session_id"))
    # Guided flow.
    try:
        groups = mgr.group_list()
    except ValueError as exc:
        return f"Group error: {exc}"
    if not groups:
        return "No groups to broadcast to. Create one with /peer-group create."
    items = []
    for g in groups:
        gid = g["group_id"]

        def _send(value, text=None, _gid=gid, _gname=g["name"]):
            if not text or not text.strip():
                return "Cancelled."
            return _do_broadcast(_gid, text, kwargs.get("session_id"))

        items.append({
            "label": f"{g['name']}  ({g['group_id'][:8]}…)  {g['members']} members",
            "value": gid,
            "detail": f"Broadcast to: {g['name']}\nid: {gid}\nmembers: {g['members']}",
            "actions": [
                {"key": "s", "label": "Compose message", "handler": _send,
                 "prompt": f"Message to broadcast to {g['name']}:"},
            ],
        })
    return {"interactive": {
        "title": "Broadcast — choose a group",
        "items": items,
        "actions": [
            {"key": "q", "label": "Close", "handler": lambda v=None, t=None: None},
        ],
    }}


def _do_broadcast(group_id: str, content: str, session_id) -> str:
    mgr = get_manager()
    try:
        result = mgr.broadcast_send(group_id, content, session_id=session_id)
        s = result["summary"]
        return (
            f"Broadcast {s['broadcast_id'][:8]}…: "
            f"{s['queued']} queued, {s['skipped']} skipped, {s['unreachable']} unreachable"
        )
    except ValueError as exc:
        return f"Broadcast error: {exc}"


def cmd_peer_request(raw: str, **kwargs) -> str | dict:
    mgr = get_manager()
    if mgr is None:
        return "hermes-peer is not active in this process."
    _usage_log("peer-request", raw, session_id=kwargs.get("session_id"))
    parts = (raw or "").split()
    if not parts:
        # Guided: choose an action.
        return {"interactive": {
            "title": "Peer request",
            "items": [
                {"label": "create  — new structured request", "value": "create",
                 "handler": _bind_sid(_request_create_handler, kwargs.get("session_id")),
                 "prompt": "agent_id summary (agent_id + text):"},
                {"label": "status  — check a request", "value": "status",
                 "handler": _bind_sid(_request_status_handler, kwargs.get("session_id")),
                 "prompt": "request_id:"},
                {"label": "respond  — accept/decline", "value": "respond",
                 "handler": _bind_sid(_request_respond_handler, kwargs.get("session_id")),
                 "prompt": "request_id action:"},
                {"label": "cancel  — withdraw", "value": "cancel",
                 "handler": _bind_sid(_request_cancel_handler, kwargs.get("session_id")),
                 "prompt": "request_id:"},
            ],
            "empty": "Choose an action.",
        }}
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


def _request_create_handler(_value=None, text=None, session_id=None):
    mgr = get_manager()
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return "Usage: <agent_id> <summary>"
    try:
        res = mgr.create_request(parts[0], parts[1], session_id=session_id)
        return f"Request {res['request_id'][:8]}… created (delivered={res['delivered']})."
    except ValueError as exc:
        return f"Request error: {exc}"


def _request_status_handler(_value=None, text=None, session_id=None):
    mgr = get_manager()
    rid = (text or "").strip()
    if not rid:
        return "Cancelled."
    try:
        st = mgr.request_status(rid, session_id=session_id)
        return f"Request {st['request_id'][:8]}… [{st['state']}] {st['summary']}"
    except ValueError as exc:
        return f"Request error: {exc}"


def _request_respond_handler(_value=None, text=None, session_id=None):
    mgr = get_manager()
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return "Usage: <request_id> <action>"
    try:
        res = mgr.request_respond(parts[0], parts[1], session_id=session_id)
        return f"Request {res['request_id'][:8]}… -> {res['state']}"
    except ValueError as exc:
        return f"Request error: {exc}"


def _request_cancel_handler(_value=None, text=None, session_id=None):
    mgr = get_manager()
    rid = (text or "").strip()
    if not rid:
        return "Cancelled."
    try:
        res = mgr.request_cancel(rid, session_id=session_id)
        return f"Request {res['request_id'][:8]}… -> {res['state']}"
    except ValueError as exc:
        return f"Request error: {exc}"


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

    usage = peer_sub.add_parser("usage", help="Show recent slash-command usage records.")
    usage.add_argument("--limit", type=int, default=10, help="How many recent records to show.")


def _render_interactive_plain(spec: dict) -> str:
    """Flatten an interactive spec into plain text for non-curses surfaces.

    Accepts either a bare spec (``{title, items, ...}``) or a wrapped one
    (``{"interactive": {...}}``) as returned by command handlers. A plain
    string passes through unchanged (commands may return strings directly).
    """
    if not isinstance(spec, dict):
        return str(spec)
    if "interactive" in spec and isinstance(spec["interactive"], dict):
        spec = spec["interactive"]
    lines = [spec.get("title", "")]
    for it in spec.get("items", []):
        lines.append(f"  {it.get('label', '')}")
        if it.get("detail"):
            for dline in it["detail"].splitlines():
                lines.append(f"    {dline}")
    actions = spec.get("actions", [])
    if actions:
        lines.append("Actions:")
        for a in actions:
            lines.append(f"  [{a.get('key', '?')}] {a.get('label', '')}")
    return "\n".join(lines)


def _usage_cli(args) -> int:
    """Print recent slash-command usage records from the JSONL log."""
    mgr = get_manager()
    if mgr is None:
        print("hermes-peer is not active in this process.")
        return 1
    root = getattr(mgr, "_paths", None)
    if root is None:
        print("no runtime paths; cannot read usage log")
        return 1
    log_path = Path(root.root) / "command-usage.jsonl"
    if not log_path.exists():
        print("No command usage recorded yet.")
        return 0
    limit = max(1, getattr(args, "limit", 10))
    records = []
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError as exc:
        print(f"Usage log error: {exc}")
        return 1
    if not records:
        print("No command usage recorded yet.")
        return 0
    print(f"Recent peer command usage (last {min(limit, len(records))} of {len(records)}):")
    for rec in records[-limit:]:
        ts = rec.get("ts", "?")[:19]
        cmd = rec.get("command", "?")
        args_txt = (rec.get("args") or "")[:40]
        sid = rec.get("session_id") or "-"
        outcome = rec.get("outcome", "ok")
        print(f"  {ts}  /{cmd:<14} {outcome:<6} sess={sid:<16} {args_txt}")
    return 0


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
    if action == "usage":
        return _usage_cli(args)
    if action == "send":
        result = peer_send_cli(mgr, args)
        print(result)
        return 0
    if action == "inbox":
        if args.action not in ("list", "release", "refuse"):
            print(f"Unknown inbox action {args.action!r}; expected list|release|refuse")
            return 2
        if args.action == "list":
            out = cmd_peer_inbox("")
            print(_render_interactive_plain(out) if isinstance(out, dict) else out)
            return 0
        if args.action == "release":
            ok = mgr.release_message(args.message_id) if args.message_id else False
            print("released" if ok else "no held message with that id")
            return 0 if ok else 1
        ok = mgr.refuse_message(args.message_id) if args.message_id else False
        print("refused" if ok else "no held message with that id")
        return 0 if ok else 1
    if action == "name":
        out = cmd_peer_name(args.name)
        print(_render_interactive_plain(out) if isinstance(out, dict) else out)
        return 0
    if action == "policy":
        out = cmd_peer_policy(args.policy)
        print(_render_interactive_plain(out) if isinstance(out, dict) else out)
        return 0
    if action == "groups":
        out = cmd_peer_groups("")
        print(_render_interactive_plain(out) if isinstance(out, dict) else out)
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
