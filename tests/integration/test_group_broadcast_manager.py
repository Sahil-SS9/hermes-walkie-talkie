"""Real-path group + broadcast + request operations (P7, P4 gate).

Three real PeerSessionManager instances share one runtime: create a group
owned by A, add B/C as members, broadcast to the group (real transport),
and confirm every member receives the message exactly once.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_peer.sessions import PeerSessionManager


class _Ctx:
    def __init__(self, home: Path) -> None:
        self.hermes_home = str(home)
        self.injected: list[tuple] = []

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        self.injected.append((content, role, mode, target_session))
        return True

    def register_hook(self, *a, **k):
        pass

    def register_command(self, *a, **k):
        pass

    def register_tool(self, *a, **k):
        pass


@pytest.fixture()
def trio(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    os.chmod(runtime_dir, 0o700)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    os.chmod(state_dir, 0o700)
    monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(state_dir))
    homes = {n: tmp_path / f"home-{n}" for n in ("a", "b", "c")}
    for h in homes.values():
        h.mkdir()
    managers = {n: PeerSessionManager(_Ctx(h), runtime_root=runtime_dir) for n, h in homes.items()}
    try:
        for n in ("a", "b", "c"):
            managers[n].on_session_open(f"sess-{n}", platform="cli")
        yield managers
    finally:
        for m in managers.values():
            m.shutdown()


def test_group_broadcast_reaches_all_members(trio):
    a, b, c = trio["a"], trio["b"], trio["c"]
    a_agent = a._peers["sess-a"].agent_id
    b_agent = b._peers["sess-b"].agent_id
    c_agent = c._peers["sess-c"].agent_id

    g = a.group_create("team", session_id="sess-a")
    assert g["owner_agent_id"] == a_agent
    a.group_add_member(g["group_id"], b_agent, session_id="sess-a")
    a.group_add_member(g["group_id"], c_agent, session_id="sess-a")

    result = a.broadcast_send(g["group_id"], "hello team", session_id="sess-a")
    summary = result["summary"]
    # The owner (a) is not a member, so b + c are the recipients.
    assert summary["queued"] == 2
    assert summary["unreachable"] == 0
    # Both members actually received the content through the real transport.
    assert any("hello team" in content for content, *_ in b._ctx.injected)
    assert any("hello team" in content for content, *_ in c._ctx.injected)


def test_group_list_and_member_ops(trio):
    a, b = trio["a"], trio["b"]
    b_agent = b._peers["sess-b"].agent_id

    g = a.group_create("list-check", session_id="sess-a")
    a.group_add_member(g["group_id"], b_agent, session_id="sess-a")
    groups = a.group_list()
    assert any(x["group_id"] == g["group_id"] and x["members"] == 1 for x in groups)
    a.group_remove_member(g["group_id"], b_agent, session_id="sess-a")
    after_remove = a.group_list()
    assert any(x["group_id"] == g["group_id"] and x["members"] == 0 for x in after_remove)
    a.group_delete(g["group_id"], session_id="sess-a")
    assert all(x["group_id"] != g["group_id"] for x in a.group_list())


def test_group_ops_fail_closed(trio):
    a = trio["a"]
    with pytest.raises(ValueError):
        a.group_add_member("missing-group", "agent-x", session_id="sess-a")
    with pytest.raises(ValueError):
        a.group_delete("missing-group", session_id="sess-a")
    # Cannot delete another owner's group.
    g = a.group_create("owned", session_id="sess-a")
    with pytest.raises(ValueError):
        trio["b"].group_delete(g["group_id"], session_id="sess-b")


def test_broadcast_empty_group_fails_closed(trio):
    a = trio["a"]
    g = a.group_create("empty", session_id="sess-a")
    with pytest.raises(ValueError):
        a.broadcast_send(g["group_id"], "nobody", session_id="sess-a")


def test_multi_session_ambiguity_fails_closed(trio):
    """P7.6: mutating ops without a session_id fail when multiple sessions."""
    a = trio["a"]
    a.on_session_open("sess-a2", platform="cli")
    try:
        with pytest.raises(ValueError):
            a.group_create("ambiguous", session_id=None)
        with pytest.raises(ValueError):
            a.broadcast_send("g", "x", session_id=None)
        with pytest.raises(ValueError):
            a.group_delete("g", session_id=None)
    finally:
        # close the extra session cleanly
        a.on_session_finalize("sess-a2", reason="test")


def test_group_ops_session_scoped(trio):
    """Group membership stores stable agent_id, never the mutable alias."""
    a, b = trio["a"], trio["b"]
    b_agent = b._peers["sess-b"].agent_id
    g = a.group_create("scoped", session_id="sess-a")
    a.group_add_member(g["group_id"], b_agent, session_id="sess-a")
    members = a._group_store().members(g["group_id"])
    assert members[0].agent_id == b_agent
    # Renaming the peer does not change membership (alias is display-only).
    b.set_alias("renamed-b", session_id="sess-b")
    members_after = a._group_store().members(g["group_id"])
    assert members_after[0].agent_id == b_agent
