"""Fuzzing, flood, concurrency and storage-failure hardening tests (SEC-1004, SEC-1008, SEC-1009, SEC-1014)."""

from __future__ import annotations

import os
import socket
import sqlite3
import stat
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_peer.codec import encode_envelope
from agent_peer.errors import AgentPeerError
from agent_peer.models import Envelope, Kind, PeerIdentity, PeerRecord, ReceiptState
from agent_peer.runtime import PeerRuntimeManager
from agent_peer.store import MessageStore

NOW = datetime.now(UTC)


def _record(name: str = "f", **kw) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name=name,
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        last_seen=datetime.now(UTC).isoformat(),
        **kw,
    )


@pytest.fixture(scope="module")
def fuzz_base(tmp_path_factory):
    return tmp_path_factory.mktemp("fuzz")


class TestPayloadFuzzing:
    """SEC-1004: truncated/oversized/nested/malformed/unknown-version input
    cannot crash the supervisor."""

    @given(st.binary(min_size=0, max_size=4096))
    @settings(max_examples=60, deadline=None)
    def test_supervisor_survives_arbitrary_bytes(self, fuzz_base, data):
        runtime_dir = fuzz_base / f"run-{uuid.uuid4().hex[:8]}"
        delivered: list[str] = []
        mgr = PeerRuntimeManager(runtime_dir)
        try:
            a = _record("alpha")
            b = _record("beta")
            mgr.register_peer(a, on_message=lambda e: delivered.append(e.content) or ReceiptState.QUEUED)
            handle_b = mgr.register_peer(b, on_message=lambda e: delivered.append(e.content) or ReceiptState.QUEUED)

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(handle_b.socket_path))
            try:
                sock.sendall(data)
                sock.sendall(b"\x00\x00\x00\x02\xff")  # truncated frame
                sock.sendall((2**31).to_bytes(4, "big"))  # oversized prefix
            finally:
                sock.close()

            # The supervisor must still serve a healthy client. Under rapid
            # supervisor create/destroy churn a first connect can transiently
            # fail; the property is that the supervisor stays available.
            sender = PeerIdentity(peer_id=a.peer_id, name="alpha", profile="")
            env = _envelope(sender, b.peer_id, "still alive")
            ok = False
            for _ in range(3):
                receipt = mgr.send(env)
                if receipt.state.value == "queued":
                    ok = True
                    break
                time.sleep(0.2)
            assert ok, "supervisor stopped serving healthy clients after fuzz input"
            # Adversarial bytes that happen to form a VALID frame are
            # legitimately delivered; the healthy message must arrive too.
            assert "still alive" in delivered
        finally:
            mgr.shutdown()

    def test_unknown_version_frame_contained(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        try:
            b = _record("beta")
            handle_b = mgr.register_peer(b, on_message=lambda e: ReceiptState.QUEUED)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(handle_b.socket_path))
            try:
                from agent_peer.codec import canonical_json

                env = _envelope(PeerIdentity(peer_id=str(uuid.uuid4()), name="x", profile=""), b.peer_id, "v9")
                raw = canonical_json(encode_envelope(env)).replace("agent-peer/1", "agent-peer/9")
                sock.sendall(len(raw.encode()).to_bytes(4, "big") + raw.encode())
            finally:
                sock.close()
            time.sleep(0.2)
            # Still available.
            a = _record("alpha")
            mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
            assert len(mgr._peers) >= 2
        finally:
            mgr.shutdown()


class TestFlood:
    """SEC-1008: rate/capacity limits keep delivery bounded."""

    def test_flood_is_rate_limited_per_pair(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        from agent_peer.policy import PolicyEngine

        engine = PolicyEngine(policy="accept", rate_burst=5, rate_per_minute=20)
        sender = PeerIdentity(peer_id=str(uuid.uuid4()), name="flooder", profile="")
        recipient = str(uuid.uuid4())
        accepted = 0
        for _ in range(500):
            decision = engine.evaluate(_envelope(sender, recipient, "flood"))
            if decision.action == "forward":
                accepted += 1
        assert accepted <= 20  # sustained cap
        # Burst gate: no more than burst in the first instant.
        engine2 = PolicyEngine(policy="accept", rate_burst=5, rate_per_minute=20)
        burst_recipient = str(uuid.uuid4())
        burst = sum(1 for _ in range(10) if engine2.evaluate(_envelope(sender, burst_recipient, "b")).action == "forward")
        assert burst == 5

    def test_capacity_bounds_store(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        store = MessageStore(runtime_dir.parent / "state" / "m.sqlite3")
        try:
            row_base = {"message_id": "", "recipient_peer_id": str(uuid.uuid4()), "sender_peer_id": str(uuid.uuid4()), "kind": "message", "content": "x", "state": "held", "created_at": NOW.isoformat(), "expires_at": (NOW + timedelta(minutes=5)).isoformat(), "hop_count": 0}
            for _ in range(120):
                row = dict(row_base, message_id=str(uuid.uuid4()))
                store.record(row)
            assert store.count_pending(row_base["recipient_peer_id"]) == 120
            # Retention bounds it.
            store.retain(max_rows=100)
            assert store.count_all() <= 100
        finally:
            store.close()


class TestConcurrencyStress:
    """SEC-1009: many senders, many sessions in one process, shutdown mid-send."""

    def test_five_peers_fifty_concurrent_sends(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        delivered: list[str] = []
        lock = threading.Lock()

        def on_msg(env):
            with lock:
                delivered.append(env.content)
            return ReceiptState.QUEUED

        peers = [_record(f"peer-{i}") for i in range(5)]
        handles = [mgr.register_peer(p, on_message=on_msg) for p in peers]
        sender = PeerIdentity(peer_id=peers[0].peer_id, name="s", profile="")
        results: list[bool] = []
        rlock = threading.Lock()

        def worker(i: int):
            target = peers[1 + (i % 4)].peer_id
            receipt = mgr.send(_envelope(sender, target, f"m-{i}"))
            with rlock:
                results.append(receipt.state.value == "queued")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        assert len(results) == 50 and all(results)
        assert len(set(delivered)) == 50  # none lost, none duplicated
        for h in handles:
            h.close()
        mgr.shutdown()

    def test_shutdown_during_send_is_safe(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        mgr = PeerRuntimeManager(runtime_dir)
        a = _record("a")
        b = _record("b")
        mgr.register_peer(a, on_message=lambda e: ReceiptState.QUEUED)
        mgr.register_peer(b, on_message=lambda e: ReceiptState.QUEUED)
        sender = PeerIdentity(peer_id=a.peer_id, name="a", profile="")
        errors: list[Exception] = []

        def sender_loop():
            try:
                for i in range(20):
                    mgr.send(_envelope(sender, b.peer_id, f"x-{i}"))
            except Exception as exc:  # noqa: BLE001 - shutdown race expected
                errors.append(exc)

        t = threading.Thread(target=sender_loop)
        t.start()
        time.sleep(0.05)
        mgr.shutdown()  # must not hang or corrupt
        t.join(timeout=10)
        # Errors are acceptable (transport closed), but they must be
        # AgentPeerError-family, never a crash of the process.
        for exc in errors:
            assert isinstance(exc, AgentPeerError), exc


class TestStorageFailures:
    """SEC-1014: disk-full/read-only/partial-write failures are observable."""

    def test_readonly_store_raises_observable_error(self, isolated_runtime):
        runtime_dir, state_dir = isolated_runtime
        db = state_dir / "messages.sqlite3"
        store = MessageStore(db)
        row = {"message_id": str(uuid.uuid4()), "recipient_peer_id": str(uuid.uuid4()), "sender_peer_id": str(uuid.uuid4()), "kind": "message", "content": "x", "state": "queued", "created_at": NOW.isoformat(), "expires_at": (NOW + timedelta(minutes=5)).isoformat(), "hop_count": 0}
        store.record(row)
        store.close()
        # Make the DB read-only and attempt a write.
        db.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        try:
            store2 = MessageStore(db)
            try:
                with pytest.raises((sqlite3.Error, Exception)):
                    store2.record(dict(row, message_id=str(uuid.uuid4())))
            finally:
                store2.close()
        finally:
            db.chmod(stat.S_IRUSR | stat.S_IWUSR)
        # Existing state is not corrupted.
        store3 = MessageStore(db)
        assert store3.get(row["message_id"]) is not None
        store3.close()

    def test_readonly_registry_dir_fails_closed(self, isolated_runtime):
        runtime_dir, _ = isolated_runtime
        from agent_peer.paths import RuntimePaths
        from agent_peer.registry import Registry

        paths = RuntimePaths(runtime_dir)  # creates + validates 0700
        reg_dir = paths.registry_dir
        reg_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # no write
        try:
            reg = Registry(paths)
            with pytest.raises(OSError):
                reg.register(_record())
        finally:
            reg_dir.chmod(0o700)


def _envelope(sender: PeerIdentity, recipient: str, content: str) -> Envelope:
    return Envelope(
        protocol="agent-peer/1",
        message_id=str(uuid.uuid4()),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        sender=sender,
        recipient_peer_id=recipient,
        kind=Kind.MESSAGE,
        content=content,
        reply_to=None,
        conversation_id=None,
        hop_count=0,
    )
