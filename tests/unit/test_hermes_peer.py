"""RED tests for the Hermes lifecycle and delivery adapter (HP-701..HP-709)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from hermes_peer.config import PeerConfig
from hermes_peer.delivery import DeliveryAdapter, peer_message_marker
from hermes_peer.plugin import host_seam_supported
from hermes_peer.sessions import PeerSessionManager

NOW = datetime.now(UTC)


class FakeCtx:
    """Minimal public PluginContext stand-in (register_hook / inject_message)."""

    def __init__(self) -> None:
        self.hooks: dict[str, list] = {}
        self.injected: list[tuple] = []
        self.seam = True

    def register_hook(self, name: str, callback) -> None:
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, *a, **kw) -> None:
        pass

    def register_command(self, *a, **kw) -> None:
        pass

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        if not self.seam:
            return False
        self.injected.append((content, role, mode, target_session))
        return True

    def fire(self, name: str, **kwargs) -> None:
        for cb in self.hooks.get(name, []):
            cb(**kwargs)


@pytest.fixture
def ctx() -> FakeCtx:
    return FakeCtx()


@pytest.fixture
def manager(ctx, isolated_runtime) -> PeerSessionManager:
    runtime_dir, _ = isolated_runtime
    mgr = PeerSessionManager(ctx, runtime_root=runtime_dir)
    yield mgr
    mgr.shutdown()


class TestSeamFeatureDetection:
    def test_supported_seam_detected(self):
        assert host_seam_supported(FakeCtx()) is True

    def test_missing_seam_detected(self):
        class OldCtx:
            def inject_message(self, content, role="user"):
                return True

        assert host_seam_supported(OldCtx()) is False


class TestConfigLoader:
    def test_defaults(self):
        cfg = PeerConfig()
        assert cfg.inbound == "accept"
        assert cfg.name == ""

    def test_loads_settings(self, ctx, monkeypatch):
        monkeypatch.setattr(
            "hermes_peer.config._load_config",
            lambda: {"plugins": {"entries": {"hermes-peer": {"settings": {"inbound": "hold", "name": "backend"}}}}},
        )
        cfg = PeerConfig.load(ctx)
        assert cfg.inbound == "hold"
        assert cfg.name == "backend"

    def test_invalid_policy_fails_clearly(self, ctx, monkeypatch):
        monkeypatch.setattr(
            "hermes_peer.config._load_config",
            lambda: {"plugins": {"entries": {"hermes-peer": {"settings": {"inbound": "broadcast"}}}}},
        )
        with pytest.raises(ValueError):
            PeerConfig.load(ctx)

    def test_missing_entries_uses_defaults(self, ctx, monkeypatch):
        monkeypatch.setattr("hermes_peer.config._load_config", lambda: {})
        cfg = PeerConfig.load(ctx)
        assert cfg.inbound == "accept"


class TestSessionLifecycle:
    def test_start_registers_peer(self, manager):
        manager.on_session_start("sess-abc", platform="cli")
        peers = manager.list_peers()
        assert len(peers) == 1
        assert peers[0].session_id == "sess-abc"
        assert peers[0].surface == "cli"
        assert peers[0].host_target == "cli:sess-abc"

    def test_two_sessions_register_independently(self, manager):
        manager.on_session_start("sess-a", platform="cli")
        manager.on_session_start("sess-b", platform="gateway")
        peers = manager.list_peers()
        assert len(peers) == 2
        targets = {p.host_target for p in peers}
        assert targets == {"cli:sess-a", "gateway:sess-b"}

    def test_end_marks_idle(self, manager):
        manager.on_session_start("sess-a", platform="cli")
        manager.on_session_start("sess-a", platform="cli")  # start again = working
        manager.on_session_end("sess-a", platform="cli")
        peers = manager.list_peers()
        assert peers[0].status == "idle"

    def test_finalize_removes_registration(self, manager):
        manager.on_session_start("sess-a", platform="cli")
        manager.on_session_finalize("sess-a", platform="cli", reason="shutdown")
        assert manager.list_peers() == []

    def test_reset_keeps_alias_and_recreates_peer(self, manager):
        manager.on_session_start("sess-old", platform="cli")
        manager.set_alias("backend")
        manager.on_session_reset("sess-new", platform="cli")
        peers = manager.list_peers()
        assert len(peers) == 1
        assert peers[0].session_id == "sess-new"
        assert peers[0].name == "backend"  # alias survives reset
        assert peers[0].host_target == "cli:sess-new"  # no stale target reuse

    def test_abnormal_exit_cleans_up(self, manager):
        manager.on_session_start("sess-a", platform="cli")
        manager.shutdown()
        assert manager.list_peers() == []


class TestDeliveryAdapter:
    def test_peer_message_marker_shape(self):
        wrapped = peer_message_marker("The API schema changed.", sender_name="architect", sender_peer_id="abc123", message_id="msg_xyz")
        assert wrapped.startswith("<peer_message>")
        assert "From: architect" in wrapped
        assert "Peer ID: abc123" in wrapped
        assert "Message ID: msg_xyz" in wrapped
        assert wrapped.endswith("</peer_message>")

    def test_delivery_uses_queue_mode_and_exact_target(self, ctx, manager):
        manager.on_session_start("sess-b", platform="cli")
        delivery = DeliveryAdapter(ctx, manager)
        env = manager._make_envelope(recipient=manager.list_peers()[0].peer_id, content="hello")
        ok = delivery.deliver(env)
        assert ok is True
        assert len(ctx.injected) == 1
        content, role, mode, target = ctx.injected[0]
        assert role == "user"
        assert mode == "queue"
        assert target == "cli:sess-b"
        assert content.startswith("<peer_message>")

    def test_delivery_to_unknown_target_returns_false(self, ctx, manager):
        manager.on_session_start("sess-a", platform="cli")
        delivery = DeliveryAdapter(ctx, manager)
        env = manager._make_envelope(recipient=str(uuid.uuid4()), content="hi")
        assert delivery.deliver(env) is False
        assert ctx.injected == []

    def test_delivery_fails_closed_without_seam(self, ctx, manager):
        ctx.seam = False
        manager.on_session_start("sess-b", platform="cli")
        delivery = DeliveryAdapter(ctx, manager)
        env = manager._make_envelope(recipient=manager.list_peers()[0].peer_id, content="hi")
        assert delivery.deliver(env) is False

    def test_duplicate_delivery_same_peer_once(self, ctx, manager):
        manager.on_session_start("sess-b", platform="cli")
        delivery = DeliveryAdapter(ctx, manager)
        recipient = manager.list_peers()[0].peer_id
        env = manager._make_envelope(recipient=recipient, content="once")
        delivery.deliver(env)
        delivery.deliver(env)  # same message_id -> deduplicated
        assert len(ctx.injected) == 1
