"""Request/group tool error branches (P11.1 coverage).

Drives every fail-closed path of the V2 tools: inactive manager,
missing required args, bad action values (with an active manager stub
so the arg-validation branches actually fire).
"""

from __future__ import annotations

import json

import pytest

import hermes_peer.tools as toolsmod
from hermes_peer.tools import (
    peer_broadcast,
    peer_group_manage,
    peer_request_cancel,
    peer_request_create,
    peer_request_respond,
    peer_request_status,
)

SID = "33333333-3333-4333-8333-333333333333"


class _StubManager:
    def create_request(self, target_agent_id, summary, *, payload=None, idempotency_key="", session_id=None):
        raise RuntimeError("stub create")
    def request_status(self, request_id, *, session_id=None):
        raise ValueError("stub status")
    def request_respond(self, request_id, action, *, detail="", session_id=None):
        raise ValueError("stub respond")
    def request_cancel(self, request_id, *, session_id=None):
        raise ValueError("stub cancel")
    def group_manage(self, action, *, group_id=None, name=None, member_agent_id=None, session_id=None):
        raise RuntimeError("stub manage")
    def broadcast_send(self, group_id, message, *, session_id=None):
        raise RuntimeError("stub broadcast")


@pytest.fixture()
def mgr(monkeypatch):
    monkeypatch.setattr(toolsmod, "get_manager", lambda: _StubManager())


class TestV2ToolErrorBranches:
    def test_request_create_inactive_manager(self, monkeypatch):
        monkeypatch.setattr(toolsmod, "get_manager", lambda: None)
        out = peer_request_create({"target_agent_id": SID, "summary": "s"}, session_id="s1")
        assert "error" in json.loads(out)

    def test_request_create_missing_args(self, mgr):
        out = peer_request_create({"target_agent_id": "  ", "summary": ""}, session_id="s1")
        assert "required" in json.loads(out)["error"]

    def test_request_status_missing_id(self, mgr):
        out = peer_request_status({"request_id": ""}, session_id="s1")
        assert "required" in json.loads(out)["error"]

    def test_request_status_exception(self, mgr):
        out = peer_request_status({"request_id": "x"}, session_id="s1")
        assert "error" in json.loads(out)

    def test_request_respond_missing_or_bad_action(self, mgr):
        out = peer_request_respond({"request_id": "x", "action": "explode"}, session_id="s1")
        assert "required" in json.loads(out)["error"]

    def test_request_respond_exception(self, mgr):
        out = peer_request_respond({"request_id": "x", "action": "accept"}, session_id="s1")
        assert "error" in json.loads(out)

    def test_request_cancel_missing_id(self, mgr):
        out = peer_request_cancel({"request_id": ""}, session_id="s1")
        assert "required" in json.loads(out)["error"]

    def test_group_manage_missing_action(self, mgr):
        out = peer_group_manage({"group_id": "g"}, session_id="s1")
        assert "action" in json.loads(out)["error"]

    def test_broadcast_inactive_manager(self, monkeypatch):
        monkeypatch.setattr(toolsmod, "get_manager", lambda: None)
        out = peer_broadcast({"group_id": "g", "message": "hi"}, session_id="s1")
        assert "error" in json.loads(out)
