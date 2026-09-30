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


class TestGatewayExactTarget:
    """E2E-905: exact-session gateway injection through the PUBLIC plugin seam.

    Pins the seam walkie actually uses at runtime:
    ``PluginContext.inject_message(content, mode="queue", session_key=...)``
    routed through the manager-owned gateway injector that the live gateway
    publishes via ``set_gateway_message_injector`` (gateway/run_inbound.py).
    Requires the Hermes candidate checkout; skipped in a clean standalone
    environment (importorskip on the core modules).
    """

    def test_busy_queued_idle_dispatched_no_leak(self, monkeypatch):
        pytest.importorskip("gateway.run")
        from datetime import datetime

        from gateway.platforms.base import MessageEvent, Platform, SessionSource
        from gateway.run import GatewayRunner
        from gateway.session import SessionEntry
        from hermes_cli.plugins import PluginContext, PluginManager
        try:
            from hermes_cli.plugins_manifest import PluginManifest
        except ImportError:  # older core layouts
            from hermes_cli.plugins import PluginManifest  # type: ignore[assignment]

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

        store_entries = {KEY_A: entry(KEY_A), KEY_B: entry(KEY_B)}

        class Adapter:
            """Minimal adapter mirroring the base busy-session contract.

            The real ``PlatformAdapter.handle_message`` routes an event for an
            ACTIVE session into ``_pending_messages`` (queued at the safe
            boundary) instead of spawning a new turn. This stub encodes that
            contract so the test pins the gateway-side queue-vs-dispatch
            decision without a full platform adapter.
            """

            def __init__(self):
                self._pending_messages = {}
                self._active_sessions = {KEY_A}

            async def handle_message(self, event):
                key = event.metadata.get("gateway_session_key") if event.metadata else None
                if key and key in self._active_sessions:
                    self._pending_messages[key] = event
                else:
                    dispatched.append(event)

        dispatched: list[MessageEvent] = []
        adapter = Adapter()

        async def adapter_handle(event):
            dispatched.append(event)

        r = GatewayRunner.__new__(GatewayRunner)
        r.session_store = type(
            "S",
            (),
            {
                "_entries": store_entries,
                "_is_session_ended_in_db": staticmethod(lambda sid: False),
                "lookup_by_session_key": staticmethod(lambda key: store_entries.get(key)),
            },
        )()
        # _dispatch_plugin_message_injection reads the async facade, which wraps
        # session_store; build it the same way the runner does.
        from gateway.session import AsyncSessionStore
        r._async_session_store = AsyncSessionStore(r.session_store)
        r.adapters = {"telegram": adapter}
        r._sessions = {}
        r._running = True
        r._draining = False
        r._background_tasks = set()
        r._gateway_loop = None  # set below inside the running loop

        # The dispatcher routes through the live adapter's handle_message.
        # The dispatcher resolves the live delivery adapter through the authz
        # mixin (sync call); stub it to return our adapter.
        import gateway.authz_mixin as _authz_mod
        import gateway.run as _run_mod
        monkeypatch.setattr(
            _authz_mod.GatewayAuthorizationMixin, "_delivery_adapter_for",
            lambda self, source: adapter, raising=False,
        )
        monkeypatch.setattr(
            _authz_mod.GatewayAuthorizationMixin, "_restored_source",
            lambda self, entry_obj: entry_obj.origin, raising=False,
        )
        monkeypatch.setattr(
            _run_mod.GatewayRunner, "_is_user_authorized_for_source",
            lambda self, source, **_kw: True, raising=False,
        )

        import asyncio

        # ``_install_plugin_message_injector`` publishes to the process-wide
        # singleton (get_plugin_manager()); the core's own suite adopts it by
        # patching ``_plugin_manager``. Mirror that here so the context and the
        # installed injector share one manager.
        manager = PluginManager()
        monkeypatch.setattr("hermes_cli.plugins._plugin_manager", manager, raising=False)
        ctx = PluginContext(
            PluginManifest(name="hermes-peer", key="hermes-peer", source="user"),
            manager,
        )
        # The live wiring (gateway/run_inbound.py::_install_plugin_message_injector).
        r._install_plugin_message_injector()

        # Plugin consent for gateway injection comes from the manager's home
        # config; patch at the same seam the core's own suite patches.
        monkeypatch.setattr(
            PluginContext, "_gateway_injection_allowed", lambda self: True,
        )

        async def run():
            loop = asyncio.get_running_loop()
            r._gateway_loop = loop
            # Busy session: routed, and the gateway side queues it (adapter has
            # KEY_A in _active_sessions) rather than dispatching a second turn.
            ok_busy = ctx.inject_message(
                "busy work", role="user", mode="queue", session_key=KEY_A,
            )
            # Idle session: dispatched through the adapter handler.
            ok_idle = ctx.inject_message(
                "idle work", role="user", mode="queue", session_key=KEY_B,
            )
            # Drain the scheduled injection task inside the SAME loop the
            # scheduler pinned (safe_schedule_threadsafe targets _gateway_loop).
            if r._background_tasks:
                await asyncio.gather(*r._background_tasks, return_exceptions=True)
                await asyncio.sleep(0)
            return ok_busy, ok_idle

        ok_busy, ok_idle = asyncio.run(run())
        assert ok_busy is True and ok_idle is True
        assert len(dispatched) == 1 and dispatched[0].text.endswith("idle work")
        assert KEY_B not in (adapter._pending_messages or {})


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
