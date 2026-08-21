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
        """V1 four slash commands preserved + V2 group/request commands."""
        assert set(env.commands) == {
            "peers",
            "peer-name",
            "peer-policy",
            "peer-inbox",
            "peer-groups",
            "peer-group",
            "peer-broadcast",
            "peer-request",
        }

    def test_peers_command_lists(self, env):
        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")
        out = env.commands["peers"]["handler"]("")
        # cmd_peers returns an interactive picker spec (dict) — verify it
        # contains the session as a selectable item.
        assert isinstance(out, dict), f"expected interactive dict, got {type(out)}"
        spec = out["interactive"]
        assert spec["items"], "expected at least one selectable peer"
        labels = " ".join(i["label"] for i in spec["items"])
        assert "cli" in labels or "sess-a" in labels

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
        out = env.commands["peer-policy"]["handler"]("hold", session_id="sess-a")
        assert "hold" in out
        assert mgr.policy_for("sess-a") == "hold"

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


class TestCliDispatch:
    def test_run_peer_cli_all_actions(self, env, capsys):
        """run_peer_cli dispatches list/send/inbox/name/policy/doctor."""
        from hermes_peer.commands import run_peer_cli

        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")

        class Args:
            peer_action = "list"

        assert run_peer_cli(Args()) == 0
        assert "Live sessions" in capsys.readouterr().out

        class Args:
            peer_action = "doctor"

        assert run_peer_cli(Args()) == 0

        target = mgr.list_peers()[0]
        target_id = target.peer_id

        class Args:
            peer_action = "send"
            target = target_id
            message = "cli test"
            reply_to = None

        capsys.readouterr()  # drain
        run_peer_cli(Args())
        assert "queued" in capsys.readouterr().out

        class Args:
            peer_action = "inbox"
            action = "list"

        run_peer_cli(Args())
        assert "Held/queued" in capsys.readouterr().out or "empty" in capsys.readouterr().out

        class Args:
            peer_action = "name"
            name = "cli-alias"

        assert run_peer_cli(Args()) == 0
        assert mgr.list_peers()[0].name == "cli-alias"

        class Args:
            peer_action = "policy"
            policy = "hold"

        assert run_peer_cli(Args()) == 0
        assert mgr.policy_for("sess-a") == "hold"

    def test_run_peer_cli_no_manager(self, capsys):
        from hermes_peer import plugin
        from hermes_peer.commands import run_peer_cli

        plugin._manager = None
        assert run_peer_cli(type("A", (), {"peer_action": "list"})()) == 1
        assert "not active" in capsys.readouterr().out
        # No manager -> any action fails closed with 1 (never crashes).
        assert run_peer_cli(type("A", (), {"peer_action": None})()) == 1

    def test_run_peer_cli_error_paths(self, env, capsys):
        """inbox release/refuse, send-to-unknown and CLI failure paths."""
        from hermes_peer.commands import run_peer_cli

        mgr = get_manager()
        mgr.on_session_start("sess-a", platform="cli")

        class Args:
            peer_action = "inbox"
            action = "release"
            message_id = "no-such-id"

        assert run_peer_cli(Args()) == 1
        assert "no held message" in capsys.readouterr().out

        class Args:
            peer_action = "inbox"
            action = "refuse"
            message_id = "no-such-id"

        assert run_peer_cli(Args()) == 1

        class Args:
            peer_action = "send"
            target = "nobody"
            message = "hi"
            reply_to = None

        out = run_peer_cli(Args())
        assert out == 0
        assert "no reachable peer" in capsys.readouterr().out

        class Args:
            peer_action = "inbox"
            action = "bogus"

        assert run_peer_cli(Args()) == 2  # unknown action falls through
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
