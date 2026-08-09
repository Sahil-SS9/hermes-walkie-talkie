"""Cross-surface E2E at the host-seam level: busy ordering, TUI/gateway
exact targeting, resume/reset safety (E2E-902, E2E-904, E2E-905, E2E-908)."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.e2e

NOW = datetime.now(UTC)


def _env(sender_peer: str, recipient: str, content: str) -> dict:
    return {
        "message_id": str(uuid.uuid4()),
        "recipient_peer_id": recipient,
        "sender_peer_id": sender_peer,
        "content": content,
    }


class TestBusyRecipient:
    def test_messages_deliver_in_order_at_safe_boundary(self, isolated_runtime):
        """E2E-902: a 'busy' handler completes before the next message is
        delivered — the active tool is never interrupted; ordering holds."""
        runtime_dir, _ = isolated_runtime
        from agent_peer.models import PeerIdentity, PeerRecord
        from agent_peer.runtime import PeerRuntimeManager

        mgr = PeerRuntimeManager(runtime_dir)
        order: list[str] = []
        lock = threading.Lock()

        def busy_handler(envelope):
            with lock:
                order.append(f"start:{envelope.content}")
                time.sleep(0.2)
                order.append(f"end:{envelope.content}")
            from agent_peer.models import ReceiptState

            return ReceiptState.QUEUED

        a = PeerRecord(peer_id=str(uuid.uuid4()), instance_id=str(uuid.uuid4()), name="a", profile="t", surface="cli", pid=1, cwd="/tmp")
        b = PeerRecord(peer_id=str(uuid.uuid4()), instance_id=str(uuid.uuid4()), name="b", profile="t", surface="cli", pid=1, cwd="/tmp")
        mgr.register_peer(a, on_message=busy_handler)
        mgr.register_peer(b, on_message=busy_handler)
        import time as _time

        from agent_peer.models import make_envelope

        sender = PeerIdentity(peer_id=a.peer_id, name="a", profile="t")
        for i in range(3):
            env = make_envelope(sender=sender, recipient_peer_id=b.peer_id, content=f"msg-{i}")
            mgr.send(env)
        _time.sleep(1.0)
        assert order == [
            "start:msg-0", "end:msg-0",
            "start:msg-1", "end:msg-1",
            "start:msg-2", "end:msg-2",
        ]
        mgr.shutdown()


class TestTuiExactTarget:
    def test_no_cross_session_leakage_idle_and_busy(self, monkeypatch):
        """E2E-904: two dashboard sessions; each receives only its own.

        Requires the Hermes candidate checkout (tui_gateway lives there);
        skipped in a clean standalone environment.
        """
        pytest.importorskip("tui_gateway.server")
        import tui_gateway.server as server

        sessions: dict[str, dict] = {}
        submitted: list[tuple[str, str]] = []
        queued: list[tuple[str, str]] = []

        monkeypatch.setattr(server, "_sessions", sessions)
        monkeypatch.setattr(server, "_sessions_lock", threading.RLock())

        def fake_run(rid, sid, session, text, **_kw):
            submitted.append((sid, str(text)))

        def fake_enqueue(session, text, transport, **_kw):
            queued.append((str(session["session_key"]), str(text)))

        monkeypatch.setattr(server, "_run_prompt_submit", fake_run)
        monkeypatch.setattr(server, "_enqueue_prompt", fake_enqueue)

        def session(key: str, running: bool):
            return {
                "agent": None,
                "session_key": key,
                "running": running,
                "transport": object(),
                "queued_prompt": None,
                "_finalized": False,
                "history_lock": threading.Lock(),
            }

        sessions["sid-1"] = session("tui:one", running=False)
        sessions["sid-2"] = session("tui:two", running=True)

        assert server.inject_external_message("to one", target_session="sid-1") is True
        assert server.inject_external_message("to two", target_session="sid-2") is True

        assert submitted == [("sid-1", "to one")]
        assert queued == [("tui:two", "to two")]


class TestGatewayExactTarget:
    def test_busy_queued_idle_dispatched_no_leak(self, monkeypatch):
        """E2E-905: one busy gateway session queues, another dispatches.

        Requires the Hermes candidate checkout (gateway lives there);
        skipped in a clean standalone environment.
        """
        pytest.importorskip("gateway.run")
        from datetime import datetime

        from gateway.platforms.base import MessageEvent, Platform, SessionSource
        from gateway.run import GatewayRunner
        from gateway.session import SessionEntry

        KEY_A = "telegram:dm:chat-a:user-1"
        KEY_B = "telegram:dm:chat-b:user-1"

        def entry(key: str) -> SessionEntry:
            return SessionEntry(
                session_key=key,
                session_id=f"sess-{key}",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                origin=SessionSource(platform=Platform.TELEGRAM, chat_id=key, chat_name="t", chat_type="dm", user_id="u", user_name="u"),
                platform=Platform.TELEGRAM,
            )

        adapter = type("A", (), {"_pending_messages": {}, "_active_sessions": {KEY_A}})()
        r = GatewayRunner.__new__(GatewayRunner)
        r.session_store = type(
            "S",
            (),
            {
                "_entries": {KEY_A: entry(KEY_A), KEY_B: entry(KEY_B)},
                "_is_session_ended_in_db": staticmethod(lambda sid: False),
            },
        )()
        r.adapters = {"telegram": adapter}
        r.config = type("C", (), {"platforms": {}})()
        r._sessions = {}
        dispatched: list[MessageEvent] = []

        async def fake_handle(event):
            dispatched.append(event)

        r._handle_message = fake_handle
        monkeypatch.setattr("gateway.run.resolve_delivery_transport", lambda p, c, a: type("T", (), {"adapter": adapter})() if p == Platform.TELEGRAM else None)
        monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"plugins": {"entries": {"hermes-peer": {"allow_gateway_injection": True}}}})

        import asyncio

        async def run():
            # Busy session: queued, not dispatched.
            ok_busy = await r.inject_plugin_message("busy work", target_session=KEY_A, plugin_id="hermes-peer")
            # Idle session: dispatched.
            ok_idle = await r.inject_plugin_message("idle work", target_session=KEY_B, plugin_id="hermes-peer")
            return ok_busy, ok_idle

        ok_busy, ok_idle = asyncio.run(run())
        assert ok_busy is True and ok_idle is True
        assert len(dispatched) == 1 and dispatched[0].text == "idle work"
        assert adapter._pending_messages[KEY_A].text == "busy work"


class TestResumeReset:
    def test_no_delivery_to_previous_route_after_rotation(self, isolated_runtime):
        """E2E-908: after reset, the stale host target is never reused."""
        runtime_dir, _ = isolated_runtime

        class FakeCtx:
            def __init__(self):
                self.injected: list[tuple] = []

            def inject_message(self, content, role="user", *, mode="queue", target_session=None):
                self.injected.append((content, target_session))
                return True

        from hermes_peer.sessions import PeerSessionManager

        ctx = FakeCtx()
        mgr = PeerSessionManager(ctx, runtime_root=runtime_dir)
        try:
            mgr.on_session_start("sess-old", platform="cli")
            old_target = mgr.list_peers()[0].host_target
            mgr.on_session_reset("sess-new", platform="cli")
            new_target = mgr.list_peers()[0].host_target
            assert old_target == "cli:sess-old"
            assert new_target == "cli:sess-new"
            assert old_target != new_target

            # A message aimed at an unknown peer must not reach the session.
            env = mgr._make_envelope(recipient=str(uuid.uuid4()), content="stale route")
            from hermes_peer.delivery import DeliveryAdapter

            assert DeliveryAdapter(ctx, mgr).deliver(env) is False
            assert ctx.injected == []
        finally:
            mgr.shutdown()
