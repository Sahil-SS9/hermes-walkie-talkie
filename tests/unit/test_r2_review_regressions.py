"""R2 RED regressions from the independent post-completion review.

These tests exercise the reviewed production seams. They must fail against the
frozen R2 base (20a6450) and pass only after the focused remediation.
"""

from __future__ import annotations

import dataclasses
import os
import socket
import stat
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.codec import FrameDecoder, encode_envelope, encode_frame
from agent_peer.discovery import DiscoveryService
from agent_peer.models import Kind, PeerIdentity, PeerRecord, Presence, ReceiptState, make_envelope
from agent_peer.paths import RuntimePaths
from agent_peer.registry import Registry
from agent_peer.runtime import PeerRuntimeManager
from agent_peer.store import MessageStore
from hermes_peer.sessions import PeerSessionManager


class FakeCtx:
    def __init__(self) -> None:
        self.injected: list[tuple] = []

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        self.injected.append((content, role, mode, target_session))
        return True


def _record(*, session_id: str = "session-a", name: str = "peer") -> PeerRecord:
    now = datetime.now(UTC).isoformat()
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        session_id=session_id,
        name=name,
        profile="test",
        surface="cli",
        host_target=f"cli:{session_id}",
        pid=os.getpid(),
        cwd="/tmp",
        status=Presence.IDLE.value,
        started_at=now,
        last_seen=now,
    )


def _message_row(message_id: str) -> dict:
    now = datetime.now(UTC)
    return {
        "message_id": message_id,
        "recipient_peer_id": str(uuid.uuid4()),
        "sender_peer_id": str(uuid.uuid4()),
        "kind": Kind.MESSAGE.value,
        "content": "one delivery",
        "state": ReceiptState.QUEUED.value,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "reply_to": None,
        "conversation_id": None,
        "delivered_at": None,
        "hop_count": 0,
    }


class TestDiscoveryIdentityFence:
    @pytest.mark.parametrize(
        ("forged_field", "forged_value"),
        [("session_id", "forged-session"), ("status", Presence.WORKING.value)],
    )
    def test_alive_must_match_every_published_identity_field(
        self, tmp_path, forged_field, forged_value
    ):
        paths = RuntimePaths(tmp_path / "runtime")
        registry = Registry(paths)
        runtime = PeerRuntimeManager(paths, registry=registry)
        record = _record()
        handle = runtime.register_peer(record, on_message=lambda _e: ReceiptState.QUEUED)
        try:
            bound = handle.record
            assert bound is not None
            registry.register(dataclasses.replace(bound, **{forged_field: forged_value}))

            visible = DiscoveryService(paths, registry=registry).list_live_peers()

            assert not visible, f"forged {forged_field} must fail closed"
        finally:
            runtime.shutdown()

    @pytest.mark.parametrize("tamper", ["record_mode", "socket_mode", "socket_inode"])
    def test_record_and_socket_authority_must_be_owner_exact(self, tmp_path, tamper):
        paths = RuntimePaths(tmp_path / "runtime")
        registry = Registry(paths)
        runtime = PeerRuntimeManager(paths, registry=registry)
        record = _record()
        handle = runtime.register_peer(record, on_message=lambda _e: ReceiptState.QUEUED)
        try:
            bound = handle.record
            assert bound is not None
            if tamper == "record_mode":
                os.chmod(paths.registry_file_for(bound.peer_id), 0o644)
            elif tamper == "socket_mode":
                os.chmod(bound.socket_path, 0o666)
            else:
                registry.register(dataclasses.replace(bound, socket_inode=bound.socket_inode + 1))

            visible = DiscoveryService(paths, registry=registry).list_live_peers()

            assert not visible, f"tampered {tamper} must fail closed"
        finally:
            runtime.shutdown()


class TestRegistrationTransaction:
    def test_supervisor_failure_rolls_back_registry_and_socket(self, tmp_path, monkeypatch):
        paths = RuntimePaths(tmp_path / "runtime")
        registry = Registry(paths)
        runtime = PeerRuntimeManager(paths, registry=registry)
        record = _record()
        monkeypatch.setattr(runtime, "_ensure_thread", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        try:
            with pytest.raises(RuntimeError, match="boom"):
                runtime.register_peer(record, on_message=lambda _e: ReceiptState.QUEUED)
            assert registry.get(record.peer_id) is None
            assert list(paths.sockets_dir.glob("*.sock")) == []
            assert runtime._peers == {}
            assert runtime._listeners == {}
        finally:
            runtime.shutdown()

    def test_registry_publish_is_after_confirmed_supervisor(self, tmp_path, monkeypatch):
        paths = RuntimePaths(tmp_path / "runtime")
        registry = Registry(paths)
        runtime = PeerRuntimeManager(paths, registry=registry)
        events: list[str] = []
        real_ensure = runtime._ensure_thread
        real_register = registry.register

        def ensure():
            events.append("supervisor")
            real_ensure()

        def publish(record):
            events.append("publish")
            real_register(record)

        monkeypatch.setattr(runtime, "_ensure_thread", ensure)
        monkeypatch.setattr(registry, "register", publish)
        handle = runtime.register_peer(_record(), on_message=lambda _e: ReceiptState.QUEUED)
        try:
            assert events == ["supervisor", "publish"]
        finally:
            handle.close()
            runtime.shutdown()

    def test_bound_socket_is_owner_only_and_instance_distinct(self, tmp_path):
        paths = RuntimePaths(tmp_path / "runtime")
        runtime = PeerRuntimeManager(paths)
        record = _record()
        handle = runtime.register_peer(record, on_message=lambda _e: ReceiptState.QUEUED)
        try:
            assert stat.S_IMODE(handle.socket_path.stat().st_mode) == 0o600
            # Socket authority must change when the instance changes even if a
            # stable peer id is deliberately reused after teardown.
            first = handle.socket_path
            handle.close()
            second_record = dataclasses.replace(record, instance_id=str(uuid.uuid4()))
            second = runtime.register_peer(second_record, on_message=lambda _e: ReceiptState.QUEUED)
            try:
                assert second.socket_path != first
            finally:
                second.close()
        finally:
            runtime.shutdown()


class TestRegistryFencedMetadata:
    def test_stale_writer_cannot_overwrite_current_authority(self, tmp_path):
        registry = Registry(RuntimePaths(tmp_path / "runtime"))
        current = dataclasses.replace(
            _record(), socket_path="/tmp/current.sock", socket_uid=os.geteuid(), socket_inode=123
        )
        registry.register(current)
        update = getattr(registry, "update_if_current", None)
        assert callable(update), "registry requires a fenced metadata update API"

        stale = update(
            current.peer_id,
            expected_instance_id=str(uuid.uuid4()),
            expected_socket_path=current.socket_path,
            expected_socket_uid=current.socket_uid,
            expected_socket_inode=current.socket_inode,
            name="stale-name",
        )
        assert stale is None
        assert registry.get(current.peer_id).name == current.name

        changed = update(
            current.peer_id,
            expected_instance_id=current.instance_id,
            expected_socket_path=current.socket_path,
            expected_socket_uid=current.socket_uid,
            expected_socket_inode=current.socket_inode,
            name="current-name",
            status=Presence.WORKING,
        )
        assert changed is not None
        assert changed.name == "current-name"
        assert changed.status == Presence.WORKING.value
        assert changed.instance_id == current.instance_id
        assert changed.socket_inode == current.socket_inode


class TestSessionIsolationR2:
    def test_two_concurrent_rotations_preserve_their_own_aliases(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        manager = PeerSessionManager(FakeCtx(), RuntimePaths(tmp_path / "runtime"))
        try:
            manager.on_session_open("session-a", platform="tui")
            manager.on_session_open("session-b", platform="tui")
            manager.set_alias("alias-a", session_id="session-a")
            manager.set_alias("alias-b", session_id="session-b")

            barrier = threading.Barrier(2)
            original_start = manager.on_session_start

            def gated_start(*args, **kwargs):
                barrier.wait(timeout=5)
                return original_start(*args, **kwargs)

            monkeypatch.setattr(manager, "on_session_start", gated_start)
            errors: list[BaseException] = []

            def rotate(old: str, new: str):
                try:
                    manager.on_session_reset(new, platform="tui", old_session_id=old)
                except BaseException as exc:  # noqa: BLE001 - collect thread failures
                    errors.append(exc)

            threads = [
                threading.Thread(target=rotate, args=("session-a", "session-a2")),
                threading.Thread(target=rotate, args=("session-b", "session-b2")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            assert not errors
            assert manager._peers["session-a2"].name == "alias-a"
            assert manager._peers["session-b2"].name == "alias-b"
            assert not hasattr(manager, "_carry_alias"), "alias transfer must not be process-global"
        finally:
            manager.shutdown()

    def test_include_self_false_excludes_every_local_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        manager = PeerSessionManager(FakeCtx(), RuntimePaths(tmp_path / "runtime"))
        try:
            manager.on_session_open("session-a", platform="tui")
            manager.on_session_open("session-b", platform="tui")
            assert manager.list_peers(include_self=False) == []
        finally:
            manager.shutdown()


class TestCrossProcessDedup:
    def test_independent_store_instances_converge_on_original_row(self, tmp_path):
        db_path = tmp_path / "state" / "messages.sqlite3"
        stores = [MessageStore(db_path) for _ in range(8)]
        barrier = threading.Barrier(len(stores))
        results: list[tuple[dict | None, bool]] = []
        errors: list[BaseException] = []
        row = _message_row(str(uuid.uuid4()))

        def claim(store: MessageStore):
            try:
                barrier.wait(timeout=5)
                results.append(store.claim(row))
            except BaseException as exc:  # noqa: BLE001 - race result is evidence
                errors.append(exc)

        threads = [threading.Thread(target=claim, args=(store,)) for store in stores]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            assert not errors
            assert [created for _existing, created in results].count(True) == 1
            assert [created for _existing, created in results].count(False) == len(stores) - 1
            duplicates = [existing for existing, created in results if not created]
            assert all(duplicate is not None for duplicate in duplicates)
            assert {duplicate["message_id"] for duplicate in duplicates if duplicate} == {row["message_id"]}
            assert stores[0].count_all() == 1
        finally:
            for store in stores:
                store.close()


class TestListenerConnectionOwnership:
    def test_unregister_a_preserves_unidentified_connection_to_b(self, tmp_path):
        paths = RuntimePaths(tmp_path / "runtime")
        runtime = PeerRuntimeManager(paths)
        handle_a = runtime.register_peer(_record(session_id="a"), lambda _e: ReceiptState.QUEUED)
        handle_b = runtime.register_peer(_record(session_id="b"), lambda _e: ReceiptState.QUEUED)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(3)
        try:
            client.connect(str(handle_b.socket_path))
            deadline = time.monotonic() + 3
            while not runtime._connections and time.monotonic() < deadline:
                time.sleep(0.01)
            assert runtime._connections, "B connection was not accepted"

            handle_a.close()

            nonce = uuid.uuid4().hex
            request = make_envelope(
                sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="probe", profile=""),
                recipient_peer_id=handle_b.peer_id,
                kind=Kind.DISCOVER,
                content="",
                conversation_id=nonce,
            )
            client.sendall(encode_frame(encode_envelope(request)))
            decoder = FrameDecoder()
            replies = list(decoder.feed(client.recv(65536)))
            assert len(replies) == 1
            assert replies[0].kind is Kind.ALIVE
            assert replies[0].conversation_id == nonce
        finally:
            client.close()
            runtime.shutdown()


class TestCoverageContract:
    def test_discovery_is_in_trust_delivery_branch_gate(self):
        from scripts.coverage_gate import TRUST_DELIVERY_MODULES

        assert "agent_peer.discovery" in TRUST_DELIVERY_MODULES
