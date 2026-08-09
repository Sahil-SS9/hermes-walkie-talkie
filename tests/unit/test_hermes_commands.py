"""RED tests for slash commands and the hermes peer CLI (HP-804..HP-808, HP-810)."""

from __future__ import annotations

import pytest

from hermes_peer.plugin import get_manager, register


class FakeCtx:
    def __init__(self) -> None:
        self.hooks: dict[str, list] = {}
        self.tools: dict[str, dict] = {}
        self.commands: dict[str, dict] = {}
        self.cli_commands: dict[str, dict] = {}

    def register_hook(self, name, callback) -> None:
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, *a, **kw) -> None:
        pass

    def register_command(self, name, handler, description="", args_hint="") -> None:
        self.commands[name] = {"handler": handler, "description": description, "args_hint": args_hint}

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description="") -> None:
        self.cli_commands[name] = {"setup_fn": setup_fn, "handler_fn": handler_fn}

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
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


class TestSlashCommands:
    def test_all_four_commands_registered(self, env):
        assert set(env.commands) == {"peers", "peer-name", "peer-policy", "peer-inbox"}

    def test_peers_command_lists(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        out = env.commands["peers"]["handler"]("")
        assert "sess-a" in out or "cli" in out

    def test_peer_name_command(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        out = env.commands["peer-name"]["handler"]("backend")
        assert "backend" in out
        peers = mgr.list_peers()
        assert peers[0].name == "backend"

    def test_peer_name_rejects_invalid(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        out = env.commands["peer-name"]["handler"]("bad name/with/slash")
        assert "invalid" in out.lower() or "error" in out.lower()

    def test_peer_policy_command(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        out = env.commands["peer-policy"]["handler"]("hold")
        assert "hold" in out
        assert mgr._policy.policy.value == "hold"

    def test_peer_policy_rejects_unknown(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        out = env.commands["peer-policy"]["handler"]("broadcast")
        assert "invalid" in out.lower()

    def test_peer_inbox_command(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        out = env.commands["peer-inbox"]["handler"]("")
        assert isinstance(out, str)


class TestCliSubcommand:
    def test_peer_cli_registered(self, env):
        assert "peer" in env.cli_commands

    def test_cli_setup_adds_subcommands(self, env):
        """`hermes peer <action>` parses for all six documented actions."""
        import argparse

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        env.cli_commands["peer"]["setup_fn"](sub)
        # Functional check: each action parses with its expected args.
        for action in ("list", "doctor"):
            args = parser.parse_args(["peer", action])
            assert args.peer_action == action
        args = parser.parse_args(["peer", "send", "peer-123", "hello", "--reply-to", "m-1"])
        assert args.peer_action == "send" and args.target == "peer-123" and args.reply_to == "m-1"
        args = parser.parse_args(["peer", "inbox", "--action", "release", "--message-id", "m-2"])
        assert args.peer_action == "inbox" and args.action == "release"
        args = parser.parse_args(["peer", "name", "backend"])
        assert args.peer_action == "name" and args.name == "backend"
        args = parser.parse_args(["peer", "policy", "hold"])
        assert args.peer_action == "policy" and args.policy == "hold"
