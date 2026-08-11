"""V1 tool compatibility tests (P7.1)."""

from __future__ import annotations

import json
import uuid

import pytest

from hermes_peer.tools import peer_list_agents, peer_read_inbox, peer_send_message


class _Record:
    def __init__(self, peer_id, name="peer") -> None:
        self.peer_id = peer_id
        self.agent_id = str(uuid.uuid4())
        self.name = name
        self.profile = ""
        self.surface = "cli"
        self.status = "idle"
        self.cwd = "/tmp"
        self.git_repo_root = ""
        self.git_branch = ""


class _Mgr:
    def __init__(self) -> None:
        self.live = [_Record(str(uuid.uuid4()))]
        self.receipts: list[dict] = []
        self.inbox: list[dict] = []

    def list_peers(self):
        return self.live

    def resolve_target(self, target):
        return next((r for r in self.live if r.peer_id == target), None), None

    def send_message(self, peer_id, message, reply_to=None, session_id=None):
        receipt = {
            "message_id": str(uuid.uuid4()),
            "state": "queued",
            "recipient_peer_id": peer_id,
            "detail": "stored",
            "delivered_at": "now",
        }
        self.receipts.append(receipt)
        return receipt

    def read_inbox(self, session_id=None):
        return self.inbox

    def release_message(self, message_id, session_id=None):
        return True

    def refuse_message(self, message_id, session_id=None):
        return True


@pytest.fixture()
def mgr(monkeypatch):
    stub = _Mgr()
    import hermes_peer.tools as toolsmod

    monkeypatch.setattr(toolsmod, "get_manager", lambda: stub)
    return stub


def test_list_agents_compat(mgr):
    result = json.loads(peer_list_agents({}))
    assert len(result["peers"]) == 1
    # V2 field present alongside V1 fields (P3 advertisement).
    assert "agent_id" in result["peers"][0]
    assert "peer_id" in result["peers"][0]


def test_send_message_compat(mgr):
    peer = mgr.live[0]
    result = json.loads(peer_send_message({"target": peer.peer_id, "message": "hi"}))
    assert result["state"] == "queued"
    assert mgr.receipts


def test_send_message_accepts_dispatcher_kwargs(mgr):
    """P7.4: every tool accepts Hermes dispatcher metadata via **kwargs."""
    peer = mgr.live[0]
    result = json.loads(
        peer_send_message(
            {"target": peer.peer_id, "message": "hi"},
            session_id="s1",
            profile="default",
        )
    )
    assert result["state"] == "queued"


def test_read_inbox_compat(mgr):
    mgr.inbox = [{"message_id": "m1", "state": "held", "content": "x", "sender_peer_id": "s"}]
    result = json.loads(peer_read_inbox({"action": "list"}))
    assert len(result["messages"]) == 1


def test_read_inbox_release_refuse(mgr):
    result = json.loads(peer_read_inbox({"action": "release", "message_id": "m1"}))
    assert result["released"] is True
    result = json.loads(peer_read_inbox({"action": "refuse", "message_id": "m1"}))
    assert result["refused"] is True
