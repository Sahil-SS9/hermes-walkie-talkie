"""Dashboard plugin API tests (P8.1..P8.3, G6.3/G6.6/G6.7).

The router is tested with a bare FastAPI TestClient against a stubbed
process-local manager — the same harness pattern the core kanban plugin
uses. Auth is delegated to the dashboard middleware at runtime; here the
routes themselves are exercised.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class _Mgr:
    """Stub manager exposing the same surface the real one does."""

    def __init__(self) -> None:
        self.groups: list[dict] = []

        class Peer:
            peer_id = "p1"
            agent_id = "a1"

        self._peers: dict[str, object] = {"s1": Peer()}

    def doctor(self):
        return {"ok": True, "backend": "posix", "metrics": {}, "problems": []}

    def metrics_snapshot(self):
        return {"delivered": 1}

    def list_peers(self):
        class R:
            peer_id = "p1"
            agent_id = "a1"
            name = "alpha"
            profile = ""
            surface = "cli"
            status = "idle"
            current_activity = "scanning arxiv"
            cwd = "/tmp"
            git_branch = ""

        return [R()]

    def summary(self):
        return {
            "total": 1,
            "active_count": 0,
            "offline_count": 0,
            "you_peer_id": "p1",
            "last_updated": "2026-08-20T12:00:00+00:00",
            "peers": [
                {
                    "peer_id": "p1",
                    "agent_id": "a1",
                    "name": "alpha",
                    "profile": "",
                    "surface": "cli",
                    "status": "idle",
                    "offline": False,
                    "status_label": "idle",
                    "current_activity": "scanning arxiv",
                    "cwd": "/tmp",
                    "git_branch": "",
                    "last_seen": "2026-08-20T12:00:00+00:00",
                }
            ],
        }

    def group_list(self):
        return self.groups

    def group_create(self, name):
        g = {"group_id": str(uuid.uuid4()), "name": name, "owner_agent_id": "o", "members": 0}
        self.groups.append(g)
        return g

    def group_add_member(self, group_id, agent_id):
        return {"group_id": group_id, "member_agent_id": agent_id, "added": True}

    def _group_store(self):
        from agent_peer.groups import GroupMember

        class S:
            def members(self, group_id):
                return [GroupMember(group_id="g1", agent_id="a1", peer_id="p1")]

        return S()

    def group_members_list(self, group_id):
        from agent_peer.groups import GroupMember

        return [
            {"agent_id": m.agent_id, "peer_id": m.peer_id}
            for m in [GroupMember(group_id=group_id, agent_id="a1", peer_id="p1")]
        ]

    def broadcast_outcomes(self, broadcast_id):
        # Unknown broadcast -> empty per_member (route raises 404).
        if broadcast_id != "b1":
            return {"broadcast_id": broadcast_id, "per_member": []}
        return {
            "broadcast_id": broadcast_id,
            "per_member": [
                {
                    "agent_id": "a1",
                    "peer_id": "p1",
                    "child_message_id": "c1",
                    "state": "completed",
                    "detail": "",
                }
            ],
        }

    def _request_store(self):
        class RS:
            def list_for_recipient(self, agent_id):
                return []

        return RS()

    def resolve_session(self, session_id=None):
        if session_id is not None and session_id not in self._peers:
            raise ValueError(f"no active peer for session {session_id!r}")
        if session_id is None:
            if len(self._peers) == 1:
                session_id = next(iter(self._peers))
            else:
                raise ValueError("no session_id supplied and multiple sessions active")
        return self._peers[session_id]

    def session_inbox(self, session_id=None):
        self.resolve_session(session_id)
        return []

    def session_requests(self, session_id=None):
        self.resolve_session(session_id)
        return []

    def read_inbox(self, session_id=None):
        return []

    def resolve_peer(self, peer_id):
        class R:
            session_id = "s1"

        # p2 = a REMOTE-shaped record: its owning session (s2) is a sibling
        # process's session, never resolvable as a local session. G8 must
        # still send to it (sender = local single session).
        if peer_id == "p2":
            return type("R2", (), {"session_id": "s2"})()
        if peer_id != "p1":
            return None
        return R()

    def send_message(self, peer_id, content, reply_to=None, session_id=None):
        if peer_id not in ("p1", "p2"):
            raise ValueError(f"no active peer with peer_id {peer_id!r}")
        return {
            "message_id": "m1",
            "state": "accepted",
            "recipient_peer_id": peer_id,
            "detail": "",
            "delivered_at": None,
        }

    def set_policy(self, policy_name, session_id=None):
        self.resolve_session(session_id)
        self.last_policy = (session_id, policy_name)

    def policy_for(self, session_id=None):
        self.resolve_session(session_id)
        return "accept"

    def request_status(self, request_id, session_id=None):
        if request_id == "missing":
            raise ValueError("unknown request")
        return {"request_id": request_id, "state": "completed", "events": []}

    def request_respond(self, request_id, action, detail="", session_id=None):
        if request_id == "missing":
            raise ValueError("unknown request")
        return {"request_id": request_id, "state": "completed"}

    def subscribe_events(self):
        return 1

    def unsubscribe_events(self, sid):
        pass

    def drain_events(self, sid):
        return []


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    import dashboard.plugin_api as api

    monkeypatch.setattr(api, "_manager", lambda: _Mgr())
    app.include_router(api.router, prefix="/api/plugins/hermes-peer")
    return TestClient(app)


def test_health(client):
    r = client.get("/api/plugins/hermes-peer/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_metrics(client):
    r = client.get("/api/plugins/hermes-peer/metrics")
    assert r.json()["delivered"] == 1


def test_peers(client):
    r = client.get("/api/plugins/hermes-peer/peers")
    assert r.json()["peers"][0]["agent_id"] == "a1"
    assert r.json()["peers"][0]["current_activity"] == "scanning arxiv"


def test_peers_summary(client):
    """G2: /peers/summary exposes the aggregate counts + you marker."""
    r = client.get("/api/plugins/hermes-peer/peers/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["active_count"] == 0
    assert body["offline_count"] == 0
    assert body["you_peer_id"] == "p1"
    assert body["last_updated"]
    assert body["peers"][0]["offline"] is False
    assert body["peers"][0]["status_label"] == "idle"
    assert body["peers"][0]["current_activity"] == "scanning arxiv"


def test_groups_empty_and_create(client):
    assert client.get("/api/plugins/hermes-peer/groups").json()["groups"] == []
    r = client.post("/api/plugins/hermes-peer/groups", json={"name": "team"})
    assert r.json()["name"] == "team"
    r = client.post("/api/plugins/hermes-peer/groups", json={"name": ""})
    assert r.status_code == 400


def test_group_members(client):
    r = client.get("/api/plugins/hermes-peer/groups/g1/members")
    assert r.json()["members"][0]["agent_id"] == "a1"
    r = client.post("/api/plugins/hermes-peer/groups/g1/members", json={"agent_id": "a2"})
    assert r.json()["added"] is True
    r = client.post("/api/plugins/hermes-peer/groups/g1/members", json={"agent_id": ""})
    assert r.status_code == 400


def test_inbox_and_requests_empty(client):
    assert client.get("/api/plugins/hermes-peer/inbox").json()["messages"] == []
    assert client.get("/api/plugins/hermes-peer/requests").json()["requests"] == []


def test_request_detail_and_respond(client):
    r = client.get("/api/plugins/hermes-peer/requests/r1")
    assert r.json()["state"] == "completed"
    r = client.get("/api/plugins/hermes-peer/requests/missing")
    assert r.status_code == 404
    r = client.post("/api/plugins/hermes-peer/requests/r1/respond", json={"action": "complete"})
    assert r.json()["state"] == "completed"
    r = client.post("/api/plugins/hermes-peer/requests/r1/respond", json={"action": "bogus"})
    assert r.status_code == 400


def test_peer_send_message(client):
    """G8: POST /peers/{peer_id}/messages delegates to mgr.send_message with
    the peer's bound session (exact-session seam)."""
    r = client.post("/api/plugins/hermes-peer/peers/p1/messages", json={"content": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "accepted"
    assert body["message_id"] == "m1"
    assert body["recipient_peer_id"] == "p1"
    r = client.post("/api/plugins/hermes-peer/peers/p1/messages", json={"content": "   "})
    assert r.status_code == 400
    r = client.post("/api/plugins/hermes-peer/peers/p1/messages", json={})
    assert r.status_code == 400
    r = client.post("/api/plugins/hermes-peer/peers/nope/messages", json={"content": "hi"})
    assert r.status_code == 404
    # G8 remote-peer fix: a record owned by a SIBLING session (s2) must still
    # be sendable — the old code 404'd because it tried to resolve s2 as a
    # local session. Sender defaults to the local single session.
    r = client.post("/api/plugins/hermes-peer/peers/p2/messages", json={"content": "hi remote"})
    assert r.status_code == 200
    assert r.json()["recipient_peer_id"] == "p2"


def test_peer_policy(client):
    """G8: POST /peers/{peer_id}/policy bridges peer_id -> session and sets
    the session-scoped policy; unknown peer -> 404, bad policy -> 400."""
    r = client.post("/api/plugins/hermes-peer/peers/p1/policy", json={"policy": "hold"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["peer_id"] == "p1"
    assert body["policy"] == "hold"
    r = client.post("/api/plugins/hermes-peer/peers/p1/policy", json={"policy": "bogus"})
    assert r.status_code == 400
    r = client.post("/api/plugins/hermes-peer/peers/nope/policy", json={"policy": "hold"})
    assert r.status_code == 404
    # G8 remote-peer fix: policy applies to the LOCAL session even when the
    # peer is a remote-shaped record (owning session s2 not resolvable locally).
    r = client.post("/api/plugins/hermes-peer/peers/p2/policy", json={"policy": "hold"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_events_websocket(client, monkeypatch):
    """The /events socket upgrades, subscribes and cleans up on close.

    (The keepalive loop is exercised implicitly; polling remains the
    authoritative fallback when sockets are unavailable — G6.7. The auth
    gate is injected here; fail-closed behaviour is covered by
    test_ws_auth_fails_closed and test_events_websocket_unauthorized_closes.)
    """
    import dashboard.plugin_api as api

    monkeypatch.setattr(api, "_ws_upgrade_authorized", lambda ws: True)
    with client.websocket_connect("/api/plugins/hermes-peer/events") as ws:
        ws.send_text("ping")
        # The handler drains then waits for the next client message; sending
        # a second ping makes it loop and send an empty events frame.
        ws.send_text("ping")
        data = ws.receive_json()
        assert "events" in data


# ---------------------------------------------------------------------------
# Edge branches (P11.1): inactive manager, empty sessions, unknown broadcast
# ---------------------------------------------------------------------------


class _NoSessionMgr(_Mgr):
    """Same stub but no active sessions (empty _peers)."""

    def __init__(self) -> None:
        self.groups = []
        self._peers: dict[str, object] = {}

    def _broadcast_store(self):
        class BS:
            def children(self, broadcast_id):
                return []

        return BS()


@pytest.fixture()
def client_no_session(monkeypatch):
    app = FastAPI()
    import dashboard.plugin_api as api

    monkeypatch.setattr(api, "_manager", lambda: _NoSessionMgr())
    app.include_router(api.router, prefix="/api/plugins/hermes-peer")
    return TestClient(app)


@pytest.fixture()
def client_inactive(monkeypatch):
    app = FastAPI()
    import dashboard.plugin_api as api
    import hermes_peer.plugin as hpp

    monkeypatch.setattr(hpp, "get_manager", lambda: None)
    app.include_router(api.router, prefix="/api/plugins/hermes-peer")
    return TestClient(app)


def test_inactive_manager_503(client_inactive):
    r = client_inactive.get("/api/plugins/hermes-peer/health")
    assert r.status_code == 503
    r = client_inactive.get("/api/plugins/hermes-peer/peers")
    assert r.status_code == 503


def test_no_session_inbox_requests(client_no_session):
    # No active session: the explicit-selection seam rejects with 400
    # rather than silently returning empty data (RISKY-2).
    r = client_no_session.get("/api/plugins/hermes-peer/inbox")
    assert r.status_code == 400
    r = client_no_session.get("/api/plugins/hermes-peer/requests")
    assert r.status_code == 400
    r = client_no_session.get("/api/plugins/hermes-peer/requests/r1")
    assert r.status_code == 400
    r = client_no_session.post("/api/plugins/hermes-peer/requests/r1/respond", json={"action": "accept"})
    assert r.status_code == 400


def test_unknown_broadcast_404(client_no_session):
    r = client_no_session.get("/api/plugins/hermes-peer/broadcasts/nope")
    assert r.status_code == 404


def test_manager_import_failure_503(monkeypatch):
    """The plugin import path failing must surface as 503, not crash."""
    import builtins

    app = FastAPI()
    import dashboard.plugin_api as api

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "hermes_peer.plugin":
            raise ImportError("plugin not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    app.include_router(api.router, prefix="/api/plugins/hermes-peer")
    r = TestClient(app).get("/api/plugins/hermes-peer/health")
    assert r.status_code == 503


def test_events_websocket_unauthorized_closes(monkeypatch):
    """When the dashboard auth gate refuses, the socket closes cleanly."""
    app = FastAPI()
    import dashboard.plugin_api as api

    monkeypatch.setattr(api, "_manager", lambda: _Mgr())
    monkeypatch.setattr(api, "_ws_upgrade_authorized", lambda ws: False)
    app.include_router(api.router, prefix="/api/plugins/hermes-peer")
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/api/plugins/hermes-peer/events"
    ) as ws:
        ws.send_text("ping")
        ws.receive_json()
