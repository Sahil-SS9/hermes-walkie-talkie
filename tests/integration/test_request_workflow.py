"""Request workflow integration tests (P5 gate, G4.4..G4.10).

Real PeerSessionManager + real transport: request queued -> accepted ->
progress -> completed, and the request arrives as inert conversational input.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hermes_peer.sessions import PeerSessionManager


class _HostCtx:
    """Host seam accepting injections (records them)."""

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
def pair(tmp_path, monkeypatch):
    """Two managers (sender + recipient) with real runtime + store."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    os.chmod(runtime_dir, 0o700)
    # Isolate the owner-local STATE dir (the store root) — never the real
    # ~/.local/state (integration tests must not mutate user state).
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    os.chmod(state_dir, 0o700)
    monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(state_dir))

    sender_home = tmp_path / "home-s"
    recipient_home = tmp_path / "home-r"
    sender_home.mkdir()
    recipient_home.mkdir()

    sctx = _HostCtx(sender_home)
    rctx = _HostCtx(recipient_home)
    sender = PeerSessionManager(sctx, runtime_root=runtime_dir)
    recipient = PeerSessionManager(rctx, runtime_root=runtime_dir)
    try:
        sender.on_session_open("s1", platform="cli")
        recipient.on_session_open("r1", platform="cli")
        yield sender, recipient, rctx
    finally:
        sender.shutdown()
        recipient.shutdown()


def test_request_full_workflow(pair):
    sender, recipient, rctx = pair
    recipient_rec = recipient._peers["r1"]
    recipient_agent = recipient_rec.agent_id

    created = sender.create_request(
        recipient_agent,
        "please summarise the inbox",
        session_id="s1",
    )
    rid = created["request_id"]

    # Recipient can see the request in its store.
    rstore = recipient._request_store()
    request = rstore.get(rid)
    assert request is not None
    assert request.recipient_agent_id == recipient_agent

    # Recipient acts: accept -> progress -> completed.
    resp = recipient.request_respond(rid, "accept", session_id="r1")
    assert resp["state"] == "accepted"
    resp = recipient.request_respond(rid, "progress", detail="started", session_id="r1")
    assert resp["state"] == "in_progress"
    resp = recipient.request_respond(rid, "complete", detail="done", session_id="r1")
    assert resp["state"] == "completed"

    # Sender polls the status with the full event timeline.
    status = sender.request_status(rid, session_id="s1")
    assert status["state"] == "completed"
    assert [e["state"] for e in status["events"]] == [
        "created", "queued", "accepted", "in_progress", "completed",
    ]


def test_request_delivered_as_inert_conversational_input(pair):
    sender, recipient, rctx = pair
    recipient_agent = recipient._peers["r1"].agent_id

    sender.create_request(recipient_agent, "do something", session_id="s1")

    # The recipient host received the request through the public seam with
    # the <peer_request> boundary — conversational input, not tool calls.
    assert rctx.injected, "recipient should have received the request"
    content, role, mode, target = rctx.injected[0]
    assert "<peer_request>" in content
    assert "</peer_request>" in content
    assert role == "user"
    assert mode == "queue"


def test_request_cannot_approve_or_invoke_controls(pair):
    """G4.9: request content is inert — it cannot approve, answer confirmations
    or invoke slash commands. The boundary marker is explicit."""
    from hermes_peer.delivery import peer_request_marker

    marker = peer_request_marker(
        "/approve dangerous-command",
        sender_name="peer",
        sender_agent_id="agent-x",
        request_id="r-1",
        summary="please approve",
    )
    # The marker wraps the payload; it is NOT a host command invocation.
    assert marker.startswith("<peer_request>")
    assert "/approve dangerous-command" in marker
    # It carries no authority: the model sees untrusted peer input.
    assert "From: peer" in marker
    assert "Request ID: r-1" in marker


def test_request_refuse_and_fail(pair):
    sender, recipient, _ = pair
    recipient_agent = recipient._peers["r1"].agent_id
    created = sender.create_request(recipient_agent, "task", session_id="s1")
    rid = created["request_id"]
    resp = recipient.request_respond(rid, "refuse", detail="busy", session_id="r1")
    assert resp["state"] == "refused"
    # Terminal: further action is a no-op.
    after = recipient.request_respond(rid, "accept", session_id="r1")
    assert after["state"] == "refused"


def test_request_idempotent_create(pair):
    sender, recipient, _ = pair
    recipient_agent = recipient._peers["r1"].agent_id
    key = "unique-op-key"
    first = sender.create_request(recipient_agent, "one", idempotency_key=key, session_id="s1")
    second = sender.create_request(recipient_agent, "one", idempotency_key=key, session_id="s1")
    assert first["request_id"] == second["request_id"]


def test_only_recipient_can_respond(pair):
    sender, recipient, _ = pair
    # Another manager tries to respond to a request not addressed to it.
    recipient_agent = recipient._peers["r1"].agent_id
    created = sender.create_request(recipient_agent, "task", session_id="s1")
    rid = created["request_id"]
    with pytest.raises(ValueError):
        sender.request_respond(rid, "accept", session_id="s1")  # sender is not recipient


def test_cancel_advisory(pair):
    sender, recipient, _ = pair
    recipient_agent = recipient._peers["r1"].agent_id
    created = sender.create_request(recipient_agent, "task", session_id="s1")
    rid = created["request_id"]
    resp = sender.request_cancel(rid, session_id="s1")
    assert resp["state"] == "cancelled"
    status = sender.request_status(rid, session_id="s1")
    assert status["state"] == "cancelled"


def test_expiry_cleanup(pair):
    sender, recipient, _ = pair
    recipient_agent = recipient._peers["r1"].agent_id
    past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    sender.create_request(recipient_agent, "late task", deadline=past, session_id="s1")
    expired = sender.request_expire_overdue()
    assert expired >= 1
