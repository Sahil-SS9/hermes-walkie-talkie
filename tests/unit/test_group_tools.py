"""Group tool tests (P7.2, G3)."""

from __future__ import annotations

import json
import uuid

import pytest

from hermes_peer.tools import peer_broadcast, peer_group_list, peer_group_manage


class _Mgr:
    """Manager stub exercising the real handler argument surface."""

    def __init__(self) -> None:
        self.groups: list[dict] = []
        self.broadcasts: list[dict] = []
        self.created: dict | None = None

    def group_list(self):
        return self.groups

    def group_create(self, name, *, session_id=None):
        g = {"group_id": str(uuid.uuid4()), "name": name, "owner_agent_id": "owner"}
        self.groups.append(g)
        return g

    def group_add_member(self, group_id, member, *, session_id=None):
        return {"group_id": group_id, "member_agent_id": member, "added": True}

    def group_remove_member(self, group_id, member, *, session_id=None):
        return {"group_id": group_id, "member_agent_id": member, "removed": True}

    def group_delete(self, group_id, *, session_id=None):
        return {"group_id": group_id, "deleted": True}

    def broadcast_send(self, group_id, message, *, session_id=None):
        result = {
            "broadcast_id": str(uuid.uuid4()),
            "summary": {"total": 1, "queued": 1, "skipped": 0, "unreachable": 0, "failures": {"count": 0, "items": []}},
            "per_member": [{"agent_id": "a", "peer_id": "p", "state": "queued"}],
        }
        self.broadcasts.append(result)
        return result


@pytest.fixture()
def mgr(monkeypatch):
    stub = _Mgr()
    import hermes_peer.tools as toolsmod

    monkeypatch.setattr(toolsmod, "get_manager", lambda: stub)
    return stub


def test_group_list(mgr):
    mgr.groups = [{"group_id": "g1", "name": "team", "owner_agent_id": "o", "members": 2}]
    result = json.loads(peer_group_list({}))
    assert result["groups"][0]["name"] == "team"


def test_group_create(mgr):
    result = json.loads(peer_group_manage({"action": "create", "name": "new-team"}))
    assert result["name"] == "new-team"
    assert mgr.groups


def test_group_add_remove_delete(mgr):
    result = json.loads(peer_group_manage({"action": "add_member", "group_id": "g1", "member_agent_id": "a1"}))
    assert result["added"] is True
    result = json.loads(peer_group_manage({"action": "remove_member", "group_id": "g1", "member_agent_id": "a1"}))
    assert result["removed"] is True
    result = json.loads(peer_group_manage({"action": "delete", "group_id": "g1"}))
    assert result["deleted"] is True


def test_group_manage_missing_args():
    result = json.loads(peer_group_manage({"action": "create"}))
    assert "error" in result
    result = json.loads(peer_group_manage({"action": "add_member", "group_id": "g1"}))
    assert "error" in result
    result = json.loads(peer_group_manage({"action": "bogus"}))
    assert "error" in result


def test_broadcast(mgr):
    result = json.loads(peer_broadcast({"group_id": "g1", "message": "hello all"}))
    assert result["broadcast_id"]
    assert result["summary"]["queued"] == 1
    assert mgr.broadcasts


def test_broadcast_missing_args():
    result = json.loads(peer_broadcast({"group_id": "g1"}))
    assert "error" in result


def test_tools_fail_closed_when_manager_inactive(monkeypatch):
    """Every tool returns an explicit error when hermes-peer is inactive."""
    import hermes_peer.tools as toolsmod

    monkeypatch.setattr(toolsmod, "get_manager", lambda: None)
    from hermes_peer.tools import (
        peer_broadcast,
        peer_group_list,
        peer_group_manage,
        peer_request_cancel,
        peer_request_create,
        peer_request_respond,
        peer_request_status,
    )

    for handler, args in (
        (peer_broadcast, {"group_id": "g", "message": "m"}),
        (peer_group_list, {}),
        (peer_group_manage, {"action": "create", "name": "x"}),
        (peer_request_create, {"target_agent_id": "a", "summary": "s"}),
        (peer_request_status, {"request_id": "r"}),
        (peer_request_respond, {"request_id": "r", "action": "accept"}),
        (peer_request_cancel, {"request_id": "r"}),
    ):
        result = json.loads(handler(args))
        assert "error" in result, f"{handler.__name__} did not fail closed"


def test_group_manage_error_branches(mgr, monkeypatch):
    """Group manage error paths: create without name, unknown action."""
    result = json.loads(peer_group_manage({"action": "add_member", "group_id": "g", "member_agent_id": ""}))
    assert "error" in result
    result = json.loads(peer_group_manage({"action": "delete", "group_id": ""}))
    assert "error" in result

    # ValueError from the manager propagates as a tool error.
    import hermes_peer.tools as toolsmod

    class _Boom:
        def group_add_member(self, *a, **k):
            raise ValueError("boom")

    monkeypatch.setattr(toolsmod, "get_manager", lambda: _Boom())
    result = json.loads(peer_group_manage({"action": "add_member", "group_id": "g", "member_agent_id": "m"}))
    assert "error" in result and "boom" in result["error"]
