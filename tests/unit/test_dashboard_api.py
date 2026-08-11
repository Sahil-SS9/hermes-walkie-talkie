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
            cwd = "/tmp"
            git_branch = ""

        return [R()]

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

    def _request_store(self):
        class RS:
            def list_for_recipient(self, agent_id):
                return []

        return RS()

    def read_inbox(self, session_id=None):
        return []

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


def test_events_websocket(client):
    """The /events socket upgrades, subscribes and cleans up on close.

    (The keepalive loop is exercised implicitly; polling remains the
    authoritative fallback when sockets are unavailable — G6.7.)
    """
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
    assert client_no_session.get("/api/plugins/hermes-peer/inbox").json()["messages"] == []
    assert client_no_session.get("/api/plugins/hermes-peer/requests").json()["requests"] == []
    r = client_no_session.get("/api/plugins/hermes-peer/requests/r1")
    assert r.status_code == 404
    r = client_no_session.post("/api/plugins/hermes-peer/requests/r1/respond", json={"action": "accept"})
    assert r.status_code == 503


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
    with pytest.raises(Exception):
        with client.websocket_connect("/api/plugins/hermes-peer/events") as ws:
            ws.send_text("ping")
            ws.receive_json()
