"""Group request parent/child aggregation tests (P5.9, G4.8).

A group request creates one parent aggregate and one independently tracked
child request per member.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_peer.groups import GroupStore
from agent_peer.requests import RequestStore
from hermes_peer.sessions import PeerSessionManager


class _HostCtx:
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
    homes = {name: tmp_path / f"home-{name}" for name in ("s", "r1", "r2")}
    for h in homes.values():
        h.mkdir()
    ctxs = {name: _HostCtx(h) for name, h in homes.items()}
    sender = PeerSessionManager(ctxs["s"], runtime_root=runtime_dir)
    recv1 = PeerSessionManager(ctxs["r1"], runtime_root=runtime_dir)
    recv2 = PeerSessionManager(ctxs["r2"], runtime_root=runtime_dir)
    try:
        sender.on_session_open("s1", platform="cli")
        recv1.on_session_open("r1", platform="cli")
        recv2.on_session_open("r2", platform="cli")
        yield sender, recv1, recv2, ctxs
    finally:
        sender.shutdown()
        recv1.shutdown()
        recv2.shutdown()


def test_group_request_creates_parent_and_children(trio):
    sender, recv1, recv2, _ = trio
    groups = GroupStore(sender._store)
    owner = sender._peers["s1"].agent_id
    r1_agent = recv1._peers["r1"].agent_id
    r2_agent = recv2._peers["r2"].agent_id

    g = groups.create_group(owner, "team")
    groups.add_member(g.group_id, r1_agent)
    groups.add_member(g.group_id, r2_agent)

    # Create the parent aggregate + one child per member.
    rstore = RequestStore(sender._store)
    parent = rstore.create(
        sender_agent_id=owner,
        recipient_agent_id=g.group_id,  # group target
        summary="please review the PR",
        deadline="2099-01-01T00:00:00+00:00",
    )
    children = []
    for member_agent in (r1_agent, r2_agent):
        child = rstore.create(
            sender_agent_id=owner,
            recipient_agent_id=member_agent,
            summary="please review the PR",
            deadline="2099-01-01T00:00:00+00:00",
            parent_request_id=parent.request_id,
        )
        children.append(child)

    # Parent + exactly two children, each independently tracked.
    assert len(children) == 2
    for child in children:
        assert child.parent_request_id == parent.request_id
        assert child.recipient_agent_id in (r1_agent, r2_agent)

    # Children transition independently.
    rstore.transition(children[0].request_id, "queued")
    rstore.transition(children[0].request_id, "accepted")
    rstore.transition(children[1].request_id, "queued")
    rstore.transition(children[1].request_id, "refused")

    assert rstore.get(children[0].request_id).state == "accepted"  # type: ignore[union-attr]
    assert rstore.get(children[1].request_id).state == "refused"  # type: ignore[union-attr]
    assert rstore.get(parent.request_id).state == "created"  # type: ignore[union-attr]
