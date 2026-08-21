"""Coverage-completing tests for tool/command error branches (REM-509).

Targets the error/edge paths in hermes_peer.tools and hermes_peer.commands
that the happy-path tests do not exercise: no-manager errors, unknown
actions, invalid policy, empty inbox, CLI send/inbox failure paths.
"""

from __future__ import annotations

import json

import pytest

from hermes_peer.plugin import get_manager, register


class FakeCtx:
    def __init__(self) -> None:
        self.hooks: dict[str, list] = {}
        self.tools: dict[str, dict] = {}
        self.injected: list[tuple] = []

    def register_hook(self, name, callback) -> None:
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, name, toolset, schema, handler, **kw) -> None:
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_command(self, *a, **kw) -> None:
        pass

    def register_cli_command(self, *a, **kw) -> None:
        pass

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        self.injected.append((content, role, mode, target_session))
        return True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    ctx = FakeCtx()
    register(ctx)
    yield ctx
    mgr = get_manager()
    if mgr is not None:
        mgr.shutdown()
        from hermes_peer import plugin

        plugin._manager = None


class TestToolErrorBranches:
    def test_no_manager_error(self, monkeypatch):
        from hermes_peer import plugin as plugin_mod
        from hermes_peer.tools import peer_list_agents, peer_read_inbox, peer_send_message

        monkeypatch.setattr(plugin_mod, "_manager", None)
        for handler in (peer_list_agents, peer_send_message, peer_read_inbox):
            out = json.loads(handler({}))
            assert "error" in out

    def test_send_missing_args(self, env):
        from hermes_peer.tools import peer_send_message

        out = json.loads(peer_send_message({}, session_id="sess-a"))
        assert "error" in out

    def test_send_unknown_target(self, env):
        from hermes_peer.tools import peer_send_message

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = json.loads(peer_send_message({"target": "nobody", "message": "hi"}, session_id="sess-a"))
        assert "error" in out

    def test_inbox_unknown_action(self, env):
        from hermes_peer.tools import peer_read_inbox

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = json.loads(peer_read_inbox({"action": "bogus"}, session_id="sess-a"))
        assert "error" in out

    def test_inbox_release_missing_id(self, env):
        from hermes_peer.tools import peer_read_inbox

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = json.loads(peer_read_inbox({"action": "release"}, session_id="sess-a"))
        assert "error" in out

    def test_inbox_release_no_held(self, env):
        from hermes_peer.tools import peer_read_inbox

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = json.loads(peer_read_inbox({"action": "release", "message_id": "nope"}, session_id="sess-a"))
        assert "error" in out

    def test_inbox_refuse_no_held(self, env):
        from hermes_peer.tools import peer_read_inbox

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = json.loads(peer_read_inbox({"action": "refuse", "message_id": "nope"}, session_id="sess-a"))
        assert "error" in out


class TestCommandErrorBranches:
    def test_no_manager(self):
        from hermes_peer import plugin as plugin_mod
        from hermes_peer.commands import cmd_peer_inbox, cmd_peer_name, cmd_peer_policy, cmd_peers

        plugin_mod._manager = None
        for handler, arg in (
            (cmd_peers, ""),
            (cmd_peer_name, "x"),
            (cmd_peer_policy, "accept"),
            (cmd_peer_inbox, ""),
        ):
            out = handler(arg)
            assert "not active" in out

    def test_peer_name_no_session(self, env):
        from hermes_peer.commands import cmd_peer_name

        # No session registered -> "No active peer session to name."
        out = cmd_peer_name("backend")
        assert "No active peer session" in out or "Invalid" in out or "not active" in out

    def test_peer_name_invalid(self, env):
        from hermes_peer.commands import cmd_peer_name

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = cmd_peer_name("bad name/with/slash", session_id="sess-a")
        assert "Invalid" in out or "error" in out.lower()

    def test_peer_policy_invalid(self, env):
        from hermes_peer.commands import cmd_peer_policy

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = cmd_peer_policy("broadcast", session_id="sess-a")
        assert "Invalid policy" in out

    def test_peer_inbox_empty(self, env):
        from hermes_peer.commands import cmd_peer_inbox

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")
        out = cmd_peer_inbox("", session_id="sess-a")
        assert "Inbox is empty" in out or "Held/queued" in out

    def test_peer_cli_send_unknown(self, env, capsys):
        from hermes_peer.commands import run_peer_cli

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")

        class Args:
            peer_action = "send"
            target = "nobody"
            message = "hi"
            reply_to = None

        out = run_peer_cli(Args())
        assert out == 0
        assert "no reachable peer" in capsys.readouterr().out

    def test_peer_cli_unknown_action(self, env, capsys):
        """REM-509: the CLI unknown-action fallthrough path."""
        from hermes_peer.commands import run_peer_cli

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")

        class Args:
            peer_action = "bogus"

        out = run_peer_cli(Args())
        assert out == 2
        assert "Usage" in capsys.readouterr().out

    def test_peer_cli_inbox_release_no_id(self, env, capsys):
        from hermes_peer.commands import run_peer_cli

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")

        class Args:
            peer_action = "inbox"
            action = "release"
            message_id = None

        out = run_peer_cli(Args())
        assert out == 1
        assert "no held message" in capsys.readouterr().out

    def test_peer_cli_inbox_unknown_action(self, env, capsys):
        from hermes_peer.commands import run_peer_cli

        mgr = get_manager()
        mgr.on_session_open("sess-a", platform="cli")

        class Args:
            peer_action = "inbox"
            action = "bogus"

        out = run_peer_cli(Args())
        assert out == 2

    def test_peer_cli_name_no_session(self, env, capsys):
        from hermes_peer.commands import run_peer_cli

        # No session registered: run_peer_cli with one session absent.
        class Args:
            peer_action = "name"
            name = "x"

        out = run_peer_cli(Args())
        assert out == 0
        captured = capsys.readouterr().out
        assert "No active peer session" in captured or "Invalid" in captured or "not active" in captured

    def test_peers_empty(self, env):
        """REM-509: /peers with no live peers returns an empty interactive spec."""
        from hermes_peer.commands import cmd_peers

        out = cmd_peers("")
        assert isinstance(out, dict), f"expected interactive dict, got {type(out)}"
        spec = out["interactive"]
        assert not spec["items"]
        assert "No live" in spec["empty"] or "not active" in str(out)
