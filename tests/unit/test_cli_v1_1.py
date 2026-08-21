"""CLI command tests for V1.1 (P7.5/P7.6, G1.7)."""

from __future__ import annotations

import json
import uuid

import pytest

from hermes_peer.commands import (
    cmd_peer_broadcast,
    cmd_peer_group,
    cmd_peer_groups,
    cmd_peer_request,
)


class _Mgr:
    def __init__(self) -> None:
        self.groups: list[dict] = []
        self.requests: list[dict] = []

    def group_list(self):
        return self.groups

    def group_create(self, name, *, session_id=None):
        g = {"group_id": str(uuid.uuid4()), "name": name, "owner_agent_id": "o"}
        self.groups.append(g)
        return g

    def group_add_member(self, group_id, member, *, session_id=None):
        return {"added": True}

    def group_remove_member(self, group_id, member, *, session_id=None):
        return {"removed": True}

    def group_delete(self, group_id, *, session_id=None):
        return {"deleted": True}

    def broadcast_send(self, group_id, message, *, session_id=None):
        bid = str(uuid.uuid4())
        return {
            "broadcast_id": bid,
            "summary": {"broadcast_id": bid, "queued": 2, "skipped": 0, "unreachable": 1, "failures": {"count": 1}},
        }

    def create_request(self, agent_id, summary, *, session_id=None, **kw):
        r = {"request_id": str(uuid.uuid4()), "state": "queued", "delivered": True}
        self.requests.append(r)
        return r

    def request_status(self, request_id, *, session_id=None):
        return {"request_id": request_id, "state": "in_progress", "summary": "task"}

    def request_respond(self, request_id, action, *, session_id=None):
        return {"request_id": request_id, "state": "completed"}
    def request_cancel(self, request_id, *, session_id=None):
        return {"request_id": request_id, "state": "cancelled"}


@pytest.fixture()
def mgr(monkeypatch):
    stub = _Mgr()
    import hermes_peer.commands as cmdmod

    monkeypatch.setattr(cmdmod, "get_manager", lambda: stub)
    return stub


def test_peer_groups_empty(mgr):
    from hermes_peer.commands import _render_interactive_plain

    out = cmd_peer_groups("")
    assert "Groups" in _render_interactive_plain(out)
    assert "Create group" in _render_interactive_plain(out)


def test_peer_group_create(mgr):
    out = cmd_peer_group("create my-team")
    assert "Created group" in out
    assert mgr.groups


def test_peer_group_add_remove_delete(mgr):
    assert "Added" in cmd_peer_group("add g1 agent-1")
    assert "Removed" in cmd_peer_group("remove g1 agent-1")
    assert "Deleted" in cmd_peer_group("delete g1")


def test_peer_group_usage_on_bad_args(mgr):
    from hermes_peer.commands import _render_interactive_plain

    # Bare /peer-group returns a guided menu (no flat Usage string).
    out = _render_interactive_plain(cmd_peer_group(""))
    assert "Group management" in out
    # `create` with no name is an incomplete direct form -> Usage hint.
    out2 = cmd_peer_group("create")
    assert "Usage" in out2


def test_peer_broadcast(mgr):
    out = cmd_peer_broadcast("g1 hello everyone")
    assert "queued" in out
    assert "unreachable" in out


def test_peer_broadcast_usage(mgr):
    from hermes_peer.commands import _render_interactive_plain

    # Bare /peer-broadcast with no group returns a guided group picker.
    out = _render_interactive_plain(cmd_peer_broadcast("g1"))
    assert "choose a group" in out or "No groups" in out


def test_peer_request_create(mgr):
    out = cmd_peer_request("create agent-1 please review")
    assert "created" in out
    assert mgr.requests


def test_peer_request_status_respond_cancel(mgr):
    assert "in_progress" in cmd_peer_request("status r1")
    assert "completed" in cmd_peer_request("respond r1 complete")
    assert "cancelled" in cmd_peer_request("cancel r1")


def test_request_usage(mgr):
    from hermes_peer.commands import _render_interactive_plain

    # Bare /peer-request now returns a guided menu listing actions.
    out = _render_interactive_plain(cmd_peer_request(""))
    assert "Peer request" in out
    assert "create" in out


def test_request_tools_error_branches(monkeypatch):
    """Request tool handlers fail closed on missing args and manager errors."""
    from hermes_peer.tools import (
        peer_request_cancel,
        peer_request_create,
        peer_request_respond,
        peer_request_status,
    )

    # Missing args.
    assert "error" in json.loads(peer_request_create({"target_agent_id": ""}))
    assert "error" in json.loads(peer_request_status({"request_id": ""}))
    assert "error" in json.loads(peer_request_respond({"request_id": "r", "action": "bogus"}))
    assert "error" in json.loads(peer_request_cancel({"request_id": ""}))

    # Manager ValueError propagates as a tool error.
    import hermes_peer.tools as toolsmod

    class _Boom:
        def request_status(self, *a, **k):
            raise ValueError("not found")

    monkeypatch.setattr(toolsmod, "get_manager", lambda: _Boom())
    result = json.loads(peer_request_status({"request_id": "r"}))
    assert "error" in result and "not found" in result["error"]


# ---------------------------------------------------------------------------
# P11.1 edge branches: inactive manager, empty name, groups rendering,
# desktop CLI, and the main dispatch table
# ---------------------------------------------------------------------------


def test_cmd_name_inactive_and_empty(monkeypatch):
    import hermes_peer.commands as cmdmod
    from hermes_peer.commands import _render_interactive_plain

    monkeypatch.setattr(cmdmod, "get_manager", lambda: None)
    assert "not active" in cmdmod.cmd_peer_name("")
    monkeypatch.setattr(cmdmod, "get_manager", lambda: _Mgr())
    # Bare /peer-name now returns a guided rename prompt.
    out = _render_interactive_plain(cmdmod.cmd_peer_name("  "))
    assert "Rename this session" in out


def test_cmd_groups_inactive_and_rendered(mgr, monkeypatch):
    import hermes_peer.commands as cmdmod
    from hermes_peer.commands import _render_interactive_plain

    monkeypatch.setattr(cmdmod, "get_manager", lambda: None)
    assert "not active" in cmdmod.cmd_peer_groups("")
    monkeypatch.setattr(cmdmod, "get_manager", lambda: mgr)
    mgr.groups = [{"name": "team", "group_id": "g12345678", "members": 2}]
    out = _render_interactive_plain(cmdmod.cmd_peer_groups(""))
    assert "team" in out and "2 members" in out


def test_cmd_group_inactive(monkeypatch):
    import hermes_peer.commands as cmdmod

    monkeypatch.setattr(cmdmod, "get_manager", lambda: None)
    assert "not active" in cmdmod.cmd_peer_group("create x")


def test_cmd_broadcast_inactive(monkeypatch):
    import hermes_peer.commands as cmdmod

    monkeypatch.setattr(cmdmod, "get_manager", lambda: None)
    assert "not active" in cmdmod.cmd_peer_broadcast("g1 hi")


def test_desktop_cli_install_remove_status(mgr, monkeypatch, tmp_path):
    import hermes_peer.commands as cmdmod
    import hermes_peer.desktop_install as di

    # Install: uses the bundled asset path; monkeypatch to a temp asset.
    assets = tmp_path / "assets" / "desktop"
    assets.mkdir(parents=True)
    (assets / "plugin.js").write_text("export default {};", encoding="utf-8")
    (assets / "style.css").write_text("", encoding="utf-8")
    monkeypatch.setattr(di, "_bundled_plugin", lambda: assets / "plugin.js")

    class Args:
        action = "install"
        home = str(tmp_path / "home")

    assert cmdmod.run_desktop_cli(mgr, Args()) == 0

    Args.action = "status"
    assert cmdmod.run_desktop_cli(mgr, Args()) == 0

    Args.action = "remove"
    assert cmdmod.run_desktop_cli(mgr, Args()) == 0
    # Second remove: not present -> exit 1.
    assert cmdmod.run_desktop_cli(mgr, Args()) == 1


def test_main_dispatch_table(mgr, monkeypatch, tmp_path, capsys):
    import hermes_peer.commands as cmdmod
    import hermes_peer.desktop_install as di

    assets = tmp_path / "assets" / "desktop"
    assets.mkdir(parents=True)
    (assets / "plugin.js").write_text("export default {};", encoding="utf-8")
    monkeypatch.setattr(di, "_bundled_plugin", lambda: assets / "plugin.js")

    class Args:
        peer_action = "groups"
        action = "install"
        name = None
        policy = None
        arg1 = arg2 = arg3 = None
        group_id = None
        message = None
        message_id = None
        home = None

    assert cmdmod.run_peer_cli(Args()) == 0

    Args.peer_action = "group"
    Args.action = "create"
    Args.arg1 = "cli-team"
    assert cmdmod.run_peer_cli(Args()) == 0

    Args.peer_action = "broadcast"
    Args.group_id = "g1"
    Args.message = "hi"
    assert cmdmod.run_peer_cli(Args()) == 0

    Args.peer_action = "request"
    Args.action = "create"
    Args.arg1 = "agent-1"
    Args.arg2 = "task"
    assert cmdmod.run_peer_cli(Args()) == 0

    Args.peer_action = "desktop"
    Args.action = "install"
    Args.home = str(tmp_path / "home")
    assert cmdmod.run_peer_cli(Args()) == 0

    Args.peer_action = "unknown"
    assert cmdmod.run_peer_cli(Args()) == 2

    # Inactive manager -> exit 1.
    monkeypatch.setattr(cmdmod, "get_manager", lambda: None)
    Args.peer_action = "groups"
    assert cmdmod.run_peer_cli(Args()) == 1

    # Desktop with no HERMES_HOME and no --home fails closed -> exit 1.
    Args.peer_action = "desktop"
    Args.action = "install"
    Args.home = None
    assert cmdmod.run_peer_cli(Args()) == 1
