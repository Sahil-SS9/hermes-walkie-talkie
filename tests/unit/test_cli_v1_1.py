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
    assert "No groups" in cmd_peer_groups("")


def test_peer_group_create(mgr):
    out = cmd_peer_group("create my-team")
    assert "Created group" in out
    assert mgr.groups


def test_peer_group_add_remove_delete(mgr):
    assert "Added" in cmd_peer_group("add g1 agent-1")
    assert "Removed" in cmd_peer_group("remove g1 agent-1")
    assert "Deleted" in cmd_peer_group("delete g1")


def test_peer_group_usage_on_bad_args(mgr):
    assert "Usage" in cmd_peer_group("")
    assert "Usage" in cmd_peer_group("create")


def test_peer_broadcast(mgr):
    out = cmd_peer_broadcast("g1 hello everyone")
    assert "queued" in out
    assert "unreachable" in out


def test_peer_broadcast_usage(mgr):
    assert "Usage" in cmd_peer_broadcast("g1")


def test_peer_request_create(mgr):
    out = cmd_peer_request("create agent-1 please review")
    assert "created" in out
    assert mgr.requests


def test_peer_request_status_respond_cancel(mgr):
    assert "in_progress" in cmd_peer_request("status r1")
    assert "completed" in cmd_peer_request("respond r1 complete")
    assert "cancelled" in cmd_peer_request("cancel r1")


def test_request_usage(mgr):
    assert "Usage" in cmd_peer_request("")
    assert "Usage" in cmd_peer_request("bogus")


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
