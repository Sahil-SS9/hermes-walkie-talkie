"""CAREFUL-1: duplicate group membership must report added:false.

Repro at final SHA ffe3687: first add True, duplicate add True, stored
member count remains 1. The contract: GroupStore.add_member returns False
for an existing member; manager returns added:false (not a ValueError,
which is reserved for an unknown group); tools and the Desktop API surface
the same value.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_peer.groups import GroupStore
from agent_peer.store import MessageStore

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _store() -> tuple[MessageStore, GroupStore]:
    ms = MessageStore(Path(tempfile.mkdtemp()) / "m.sqlite3")
    gs = GroupStore(ms)
    return ms, gs


class TestDuplicateGroupAdd:
    def test_store_duplicate_returns_false(self):
        _, gs = _store()
        g = gs.create_group(A, "team")
        assert gs.add_member(g.group_id, B) is True
        assert gs.add_member(g.group_id, B) is False
        assert len(gs.members(g.group_id)) == 1

    def test_store_unknown_group_returns_false(self):
        _, gs = _store()
        assert gs.add_member("no-such-group", B) is False

    def test_manager_duplicate_returns_added_false(self, monkeypatch, tmp_path):
        from hermes_peer.sessions import PeerSessionManager

        class Ctx:
            pass

        monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir(exist_ok=True)
        mgr = PeerSessionManager(
            ctx=Ctx(),
            runtime_root=tmp_path / "runtime",
        )
        mgr.on_session_start("sess-1", platform="cli")
        g = mgr.group_create("team", session_id="sess-1")
        first = mgr.group_add_member(g["group_id"], B, session_id="sess-1")
        assert first["added"] is True
        dup = mgr.group_add_member(g["group_id"], B, session_id="sess-1")
        assert dup["added"] is False
        # The group still exists; an unknown group raises ValueError.
        with pytest.raises(ValueError, match="unknown group"):
            mgr.group_add_member("no-such-group", B, session_id="sess-1")

    def test_tool_surfaces_added_false(self, monkeypatch):
        import json

        import hermes_peer.tools as toolsmod

        class _Mgr:
            def group_add_member(self, group_id, member_agent_id, *, session_id=None):
                if group_id == "dup":
                    return {"group_id": "dup", "member_agent_id": member_agent_id, "added": False}
                return {"group_id": group_id, "member_agent_id": member_agent_id, "added": True}

        monkeypatch.setattr(toolsmod, "get_manager", lambda: _Mgr())
        out = json.loads(toolsmod.peer_group_manage({"action": "add_member", "group_id": "dup", "member_agent_id": B}))
        assert out["added"] is False
        out = json.loads(toolsmod.peer_group_manage({"action": "add_member", "group_id": "new", "member_agent_id": B}))
        assert out["added"] is True

    def test_dashboard_surfaces_added_false(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import dashboard.plugin_api as api

        class _Mgr:
            def __init__(self):
                self.groups = []

            def group_add_member(self, group_id, agent_id):
                if group_id == "dup":
                    return {"group_id": "dup", "member_agent_id": agent_id, "added": False}
                return {"group_id": group_id, "member_agent_id": agent_id, "added": True}

        monkeypatch.setattr(api, "_manager", lambda: _Mgr())
        app = FastAPI()
        app.include_router(api.router, prefix="/api/plugins/hermes-peer")
        client = TestClient(app)
        r = client.post("/api/plugins/hermes-peer/groups/dup/members", json={"agent_id": B})
        assert r.status_code == 200
        assert r.json()["added"] is False
