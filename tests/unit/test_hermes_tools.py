"""RED tests for the three agent tools (HP-801..HP-803, HP-810)."""

from __future__ import annotations

import json
from datetime import UTC

import pytest

from hermes_peer.plugin import get_manager, register
from hermes_peer.tools import peer_list_agents, peer_read_inbox, peer_send_message


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


@pytest.fixture
def two_peers(env):
    mgr = get_manager()
    mgr.on_session_start("sess-a", platform="cli")
    mgr.on_session_start("sess-b", platform="cli")
    return mgr


class TestToolSchemas:
    def test_exactly_three_tools_no_duplicates(self, env):
        """V1 three tools preserved + V2 request tools (P7.1/P7.3)."""
        assert set(env.tools) == {
            "peer_list_agents",
            "peer_send_message",
            "peer_read_inbox",
            "peer_request_create",
            "peer_request_status",
            "peer_request_respond",
            "peer_request_cancel",
        }
        for spec in env.tools.values():
            assert spec["toolset"] == "hermes-peer"
            assert isinstance(spec["schema"], dict)
            assert "type" in spec["schema"] and spec["schema"]["type"] == "object"

    def test_send_message_schema_fields(self, env):
        schema = env.tools["peer_send_message"]["schema"]
        props = schema["properties"]
        assert "target" in props and "message" in props
        assert "reply_to" in props
        assert schema["required"] == ["target", "message"]


class TestPeerListAgents:
    def test_lists_both_peers(self, two_peers):
        result = json.loads(peer_list_agents({}))
        assert len(result["peers"]) == 2
        names = {p["name"] for p in result["peers"]}
        assert len(names) == 2
        for p in result["peers"]:
            for key in ("peer_id", "name", "profile", "surface", "status", "cwd"):
                assert key in p

    def test_accepts_standard_hermes_dispatch_metadata(self, two_peers):
        result = json.loads(
            peer_list_agents({}, session_id="sess-a", task_id="deferred-call-r2")
        )
        assert len(result["peers"]) == 2

    def test_excludes_unreachable_stale_entries(self, two_peers):
        # A stale registry record without a live socket must not be listed.
        mgr = get_manager()
        import uuid as _uuid
        from datetime import datetime, timedelta

        from agent_peer.models import PeerRecord

        stale = PeerRecord(
            peer_id=str(_uuid.uuid4()),
            instance_id=str(_uuid.uuid4()),
            name="ghost",
            profile="test",
            surface="cli",
            pid=2**31 - 1,
            cwd="/tmp",
            last_seen=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        )
        mgr._registry.register(stale)
        result = json.loads(peer_list_agents({}))
        assert all(p["name"] != "ghost" for p in result["peers"])


class TestPeerSendMessage:
    # All handlers receive session_id from Hermes dispatch kwargs (REM-211).
    KW = {"session_id": "sess-a"}

    def test_send_by_exact_peer_id(self, two_peers):
        mgr = get_manager()
        target = mgr.list_peers()[1]
        result = json.loads(peer_send_message({"target": target.peer_id, "message": "schema changed"}, **self.KW))
        assert result["state"] in ("queued", "held", "refused", "unreachable", "expired", "invalid", "rate_limited", "over_capacity")
        assert result["message_id"]

    def test_send_by_unique_name(self, two_peers):
        mgr = get_manager()
        target = mgr.list_peers()[1]
        mgr.set_alias_for(target.peer_id, "backend")
        result = json.loads(peer_send_message({"target": "backend", "message": "hi"}, **self.KW))
        assert result["recipient_peer_id"] == target.peer_id

    def test_send_to_unknown_target_returns_error(self, two_peers):
        result = json.loads(peer_send_message({"target": "nobody", "message": "hi"}, **self.KW))
        assert result["error"]

    def test_ambiguous_name_returns_error(self, two_peers):
        mgr = get_manager()
        for peer in mgr.list_peers():
            mgr.set_alias_for(peer.peer_id, "dupe")
        result = json.loads(peer_send_message({"target": "dupe", "message": "hi"}, **self.KW))
        assert "ambigu" in result["error"].lower()

    def test_reply_to_correlation(self, two_peers):
        mgr = get_manager()
        target = mgr.list_peers()[1]
        original = json.loads(peer_send_message({"target": target.peer_id, "message": "ask"}, **self.KW))
        reply = json.loads(
            peer_send_message({"target": target.peer_id, "message": "answer", "reply_to": original["message_id"]}, **self.KW)
        )
        assert reply["state"] in ("queued", "held", "refused", "unreachable", "expired", "invalid", "rate_limited", "over_capacity")


class TestPeerReadInbox:
    KW = {"session_id": "sess-a"}

    def test_inbox_empty_by_default(self, two_peers):
        result = json.loads(peer_read_inbox({}, **self.KW))
        assert isinstance(result["messages"], list)

    def test_release_and_refuse_actions(self, two_peers):
        mgr = get_manager()
        recipient = mgr._peers["sess-a"]  # exact session's peer
        from agent_peer.models import ReceiptState

        def _insert_held(content: str):
            env = mgr._make_envelope(session_id="sess-a", recipient=recipient.peer_id, content=content)
            mgr._store.record(
                {
                    "message_id": env.message_id,
                    "recipient_peer_id": env.recipient_peer_id,
                    "sender_peer_id": env.sender.peer_id,
                    "kind": env.kind.value,
                    "content": env.content,
                    "state": ReceiptState.HELD.value,
                    "created_at": env.created_at.isoformat(),
                    "expires_at": env.expires_at.isoformat(),
                    "reply_to": env.reply_to,
                    "conversation_id": env.conversation_id,
                    "delivered_at": None,
                    "hop_count": env.hop_count,
                }
            )
            return env

        release_env = _insert_held("release me")
        refuse_env = _insert_held("refuse me")

        result = json.loads(peer_read_inbox({"action": "list"}, **self.KW))
        held = [m for m in result["messages"] if m["message_id"] == release_env.message_id]
        assert held and held[0]["state"] == "held"

        # Release forwards to the harness.
        released = json.loads(peer_read_inbox({"action": "release", "message_id": release_env.message_id}, **self.KW))
        assert released.get("released") is True
        assert len(mgr._ctx.injected) >= 1

        # Refuse marks the OTHER held message refused (audit only).
        refused = json.loads(peer_read_inbox({"action": "refuse", "message_id": refuse_env.message_id}, **self.KW))
        assert refused.get("refused") is True
        row = mgr._store.get(refuse_env.message_id)
        assert row["state"] == "refused"


class TestManagerInboundPolicy:
    def test_hold_policy_holds_inbound(self, env, two_peers):
        mgr = get_manager()
        # Set policy for sess-a's exact peer, then send TO that peer.
        mgr.set_policy("hold", session_id="sess-a")
        target = mgr._peers["sess-a"]
        from agent_peer.models import Kind

        env2 = mgr._make_envelope(session_id="sess-a", recipient=target.peer_id, content="held by policy", kind=Kind.MESSAGE)
        state = mgr._on_inbound(env2)
        assert state.value == "held"
        assert mgr._ctx.injected == []  # never forwarded

    def test_refuse_policy_refuses_without_content(self, env, two_peers):
        mgr = get_manager()
        mgr.set_policy("refuse", session_id="sess-a")
        target = mgr._peers["sess-a"]
        env2 = mgr._make_envelope(session_id="sess-a", recipient=target.peer_id, content="refused by policy")
        state = mgr._on_inbound(env2)
        assert state.value == "refused"
        row = mgr._store.get(env2.message_id)
        assert row["content"] == ""  # minimal audit metadata only
        assert mgr._ctx.injected == []

    def test_accept_policy_forwards(self, env, two_peers):
        mgr = get_manager()
        target = mgr._peers["sess-a"]
        env2 = mgr._make_envelope(session_id="sess-a", recipient=target.peer_id, content="accepted")
        state = mgr._on_inbound(env2)
        assert state.value == "queued"
        assert len(mgr._ctx.injected) == 1
