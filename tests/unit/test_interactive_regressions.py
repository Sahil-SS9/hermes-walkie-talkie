"""Regression tests for the interactive slash-command fixes.

Covers:
- Multi-session hosts: per-peer Rename/Policy actions must bind the invoking
  session (previously raised "no session_id supplied and multiple sessions
  active").
- Usage logging: every command invocation appends to command-usage.jsonl and
  `hermes peer usage` displays it.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def mgr():
    """A real PeerSessionManager with two sessions (multi-session host)."""
    from hermes_peer import plugin
    from hermes_peer.sessions import PeerSessionManager

    d = tempfile.mkdtemp()
    os.environ["AGENT_PEER_STATE_DIR"] = d + "/state"
    os.environ["XDG_STATE_HOME"] = d + "/state"
    os.environ["HERMES_HOME"] = d + "/home"

    class Ctx:
        pass

    m = PeerSessionManager(ctx=Ctx(), runtime_root=Path(d + "/runtime"))
    plugin._manager = m
    m.on_session_open("sess-A", platform="cli", profile="default")
    m.on_session_start("sess-A", platform="cli")
    m.on_session_open("sess-B", platform="cli", profile="default")
    m.on_session_start("sess-B", platform="cli")
    yield m
    try:
        m.shutdown()
    except Exception:
        pass
    finally:
        # Reset the module global so later tests' register(ctx) is not skipped.
        plugin._manager = None


def test_peers_rename_binds_invoking_session(mgr):
    """Per-peer Rename action must work on a multi-session host."""
    from hermes_peer.commands import cmd_peers

    out = cmd_peers("", session_id="sess-A")
    assert isinstance(out, dict), f"expected interactive dict, got {type(out)}"
    item0 = out["interactive"]["items"][0]
    rename = [a for a in item0["actions"] if a["key"] == "r"][0]
    result = rename["handler"](item0["value"], "newname")
    assert "Renamed to 'newname'" in result, result


def test_peers_send_binds_invoking_session(mgr):
    """Per-peer Send action must work on a multi-session host.

    Regression: previously raised 'no session_id supplied and multiple
    sessions active' — Send/Inbox closures were not threaded with the
    invoking session_id.
    """
    from hermes_peer.commands import cmd_peers

    out = cmd_peers("", session_id="sess-A")
    # Pick a peer that is NOT the invoking session (target B).
    own = mgr.peer_id_for_session("sess-A")
    target = next(i for i in out["interactive"]["items"] if i["value"] != own)
    send = [a for a in target["actions"] if a["key"] == "s"][0]
    result = send["handler"](target["value"], "hello there")
    assert result.startswith("Sent:"), result


def test_peers_inbox_binds_invoking_session(mgr):
    """Per-peer Inbox action must work on a multi-session host."""
    from hermes_peer.commands import cmd_peers

    out = cmd_peers("", session_id="sess-A")
    own = mgr.peer_id_for_session("sess-A")
    target = next(i for i in out["interactive"]["items"] if i["value"] != own)
    inbox = [a for a in target["actions"] if a["key"] == "i"][0]
    result = inbox["handler"](target["value"])
    assert "inbox" in result.lower(), result


def test_peers_policy_binds_invoking_session(mgr):
    """Per-peer Policy action (children flow) must work multi-session."""
    from hermes_peer.commands import cmd_peers

    out = cmd_peers("", session_id="sess-A")
    item0 = out["interactive"]["items"][0]
    policy = [a for a in item0["actions"] if a["key"] == "p"][0]
    children = policy["children"]["interactive"]
    chosen = children["items"][1]["value"]  # hold
    result = policy["handler"](item0["value"], chosen)
    assert "Policy set to hold" in result, result
    # The invoking session's policy changed, not the other session's.
    assert mgr.policy_for("sess-A") == "hold"


def test_usage_log_written_on_command(mgr):
    """Every command invocation appends a JSONL usage record."""
    from hermes_peer.commands import cmd_peer_name, cmd_peers

    cmd_peers("", session_id="sess-A")
    cmd_peer_name("cli-alias", session_id="sess-A")

    log_path = Path(mgr._paths.root) / "command-usage.jsonl"
    assert log_path.exists(), "usage log not written"
    lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    commands = [r["command"] for r in lines]
    assert "peers" in commands
    assert "peer-name" in commands
    rec = next(r for r in lines if r["command"] == "peer-name")
    assert rec["session_id"] == "sess-A"
    assert rec["args"] == "cli-alias"


def test_usage_cli_displays_records(mgr, capsys):
    """`hermes peer usage` prints recent records."""
    from hermes_peer.commands import _usage_cli, cmd_peers

    cmd_peers("", session_id="sess-A")

    class Args:
        limit = 10

    rc = _usage_cli(Args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "peers" in out
    assert "Recent peer command usage" in out
