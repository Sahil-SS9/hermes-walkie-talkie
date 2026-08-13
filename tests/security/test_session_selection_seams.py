"""RISKY-2/RISKY-3: explicit session selection + public query seams.

The Dashboard must never reach into manager private state (_peers,
_group_store(), _request_store(), _store._conn) or silently pick the
first session when multiple are active. The manager exposes:

- resolve_session(session_id=None) -> PeerRecord (unambiguous selection:
  explicit id, or the single active session; raises when ambiguous)
- group_members_list(group_id) -> list[dict]
- broadcast_outcomes(broadcast_id) -> dict
- session_inbox(session_id=None) -> list[dict]
- session_requests(session_id=None) -> list[dict]

Dashboard routes accept an optional session_id query parameter and pass
it through; no private attribute is referenced.
"""

from __future__ import annotations

import pytest


class _Ctx:
    pass


@pytest.fixture()
def mgr(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    from hermes_peer.sessions import PeerSessionManager

    return PeerSessionManager(ctx=_Ctx(), runtime_root=tmp_path / "runtime")


class TestResolveSession:
    def test_single_session_resolves(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        rec = mgr.resolve_session(None)
        assert rec.peer_id is not None

    def test_explicit_session_resolves(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        rec = mgr.resolve_session("sess-b")
        assert rec.peer_id is not None

    def test_multiple_sessions_ambiguous_raises(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        with pytest.raises(ValueError, match="session_id"):
            mgr.resolve_session(None)

    def test_no_session_raises(self, mgr):
        with pytest.raises(ValueError, match="no active session"):
            mgr.resolve_session(None)

    def test_unknown_session_raises(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        with pytest.raises(ValueError, match="no active peer"):
            mgr.resolve_session("nope")


class TestPublicQuerySeams:
    def test_group_members_list(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        g = mgr.group_create("team", session_id="sess-a")
        a1 = "11111111-1111-4111-8111-111111111111"
        mgr.group_add_member(g["group_id"], a1, session_id="sess-a")
        members = mgr.group_members_list(g["group_id"])
        assert {"agent_id": a1, "peer_id": ""} in members
        assert mgr.group_members_list("missing") == []

    def test_broadcast_outcomes(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        # A broadcast with no members: outcomes is an empty per_member list
        # (no crash on unknown store state).
        out = mgr.broadcast_outcomes("missing")
        assert "per_member" in out
        assert out["per_member"] == []

    def test_session_inbox_scoped(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        msgs_a = mgr.session_inbox("sess-a")
        msgs_b = mgr.session_inbox("sess-b")
        assert isinstance(msgs_a, list)
        assert isinstance(msgs_b, list)

    def test_session_requests_scoped(self, mgr):
        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        reqs_a = mgr.session_requests("sess-a")
        reqs_b = mgr.session_requests("sess-b")
        assert isinstance(reqs_a, list)
        assert isinstance(reqs_b, list)


class TestDashboardThinAdapter:
    def test_inbox_route_explicit_session(self, mgr, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import dashboard.plugin_api as api

        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        monkeypatch.setattr(api, "_manager", lambda: mgr)
        app = FastAPI()
        app.include_router(api.router, prefix="/api/plugins/hermes-peer")
        client = TestClient(app)
        r = client.get("/api/plugins/hermes-peer/inbox?session_id=sess-a")
        assert r.status_code == 200
        assert "messages" in r.json()

    def test_inbox_route_ambiguous_without_session(self, mgr, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import dashboard.plugin_api as api

        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        monkeypatch.setattr(api, "_manager", lambda: mgr)
        app = FastAPI()
        app.include_router(api.router, prefix="/api/plugins/hermes-peer")
        client = TestClient(app)
        r = client.get("/api/plugins/hermes-peer/inbox")
        assert r.status_code == 400
        assert "session_id" in r.json()["detail"]

    def test_requests_route_explicit_session(self, mgr, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import dashboard.plugin_api as api

        mgr.on_session_start("sess-a", platform="cli")
        mgr.on_session_start("sess-b", platform="cli")
        monkeypatch.setattr(api, "_manager", lambda: mgr)
        app = FastAPI()
        app.include_router(api.router, prefix="/api/plugins/hermes-peer")
        client = TestClient(app)
        r = client.get("/api/plugins/hermes-peer/requests?session_id=sess-a")
        assert r.status_code == 200
        assert "requests" in r.json()

    def test_dashboard_has_no_private_state_references(self):
        import dashboard.plugin_api as api

        with open(api.__file__, encoding="utf-8") as fh:
            src = fh.read()
        # Attribute access on the manager object: mgr._peers, ._group_store()
        # ._request_store(), ._store.* (bare method names like list_peers
        # legitimately contain the substring but are public API).
        for pattern in (
            "mgr._peers",
            "._group_store()",
            "._request_store()",
            "_store._conn",
            "._store._lock",
        ):
            assert pattern not in src, f"Dashboard must not reach {pattern!r}"
