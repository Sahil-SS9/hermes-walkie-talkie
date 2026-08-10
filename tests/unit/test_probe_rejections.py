"""Probe-rejection coverage (REM-509): _probe_once failure paths and
resolve_peer error branches that push line coverage over 90%."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest

from agent_peer.models import PeerRecord
from agent_peer.paths import RuntimePaths


def _record(**kw) -> PeerRecord:
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        name="peer",
        profile="test",
        surface="cli",
        pid=os.getpid(),
        cwd="/tmp",
        status="idle",
        **kw,
    )


class _RawSock:
    """A bare AF_UNIX listener that replies with raw bytes or silence."""

    def __init__(self, tmp_path: Path, reply: bytes | None = None, delay: float = 0.0) -> None:
        self.path = tmp_path / f"raw-{uuid.uuid4().hex[:6]}.sock"
        self.reply = reply
        self.delay = delay
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(str(self.path))
        self.srv.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self.srv.accept()
            if self.reply is not None:
                if self.delay:
                    time.sleep(self.delay)
                conn.sendall(self.reply)
            else:
                time.sleep(self.delay)  # never reply -> timeout
            conn.close()
        except OSError:
            pass

    def close(self) -> None:
        self.srv.close()
        with suppress(OSError):
            self.path.unlink()


class TestProbeRejections:
    @pytest.mark.parametrize(
        "tamper",
        [
            "kind",
            "invalid_json",
            "non_object",
            "nonce",
            "peer_id",
            "instance_id",
            "session_id",
            "protocol",
            "status",
        ],
    )
    def test_probe_rejects_each_mismatched_alive_identity_field(
        self, tmp_path, monkeypatch, tamper
    ):
        from agent_peer.codec import encode_envelope, encode_frame
        from agent_peer.discovery import _probe_once
        from agent_peer.models import Kind, PeerIdentity, make_envelope

        monkeypatch.setattr(
            "agent_peer.discovery.secrets.token_hex", lambda _size: "probe-nonce"
        )
        record = _record()
        identity = {
            "nonce": "probe-nonce",
            "peer_id": record.peer_id,
            "instance_id": record.instance_id,
            "session_id": record.session_id,
            "protocol": record.protocol,
            "status": record.status,
        }
        kind = Kind.ALIVE
        content: str = json.dumps(identity)
        if tamper == "kind":
            kind = Kind.MESSAGE
        elif tamper == "invalid_json":
            content = "{not-json"
        elif tamper == "non_object":
            content = "[]"
        else:
            identity[tamper] = f"wrong-{tamper}"
            content = json.dumps(identity)

        reply = make_envelope(
            sender=PeerIdentity(peer_id=record.peer_id, name="peer", profile="test"),
            recipient_peer_id=str(uuid.uuid4()),
            kind=kind,
            content=content,
            conversation_id="probe-nonce",
        )
        raw = _RawSock(tmp_path, reply=encode_frame(encode_envelope(reply)))
        try:
            assert _probe_once(replace(record, socket_path=str(raw.path))) is None
        finally:
            raw.close()

    def test_probe_rejects_garbage_reply(self, tmp_path):
        from agent_peer.discovery import _probe_once

        raw = _RawSock(tmp_path, reply=b"not-a-frame")
        try:
            rec = _record(socket_path=str(raw.path))
            assert _probe_once(rec) is None
        finally:
            raw.close()

    def test_probe_rejects_wrong_nonce(self, tmp_path):
        from agent_peer.discovery import _probe_once
        from agent_peer.models import Kind, PeerIdentity, make_envelope

        # Reply with an ALIVE envelope carrying a DIFFERENT nonce.
        env = make_envelope(
            sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="x", profile=""),
            recipient_peer_id=str(uuid.uuid4()),
            kind=Kind.ALIVE,
            content=json.dumps({"nonce": "wrong", "peer_id": "x"}),
            conversation_id="different",
        )
        from agent_peer.codec import encode_envelope, encode_frame

        payload = encode_frame(encode_envelope(env))
        raw = _RawSock(tmp_path, reply=payload)
        try:
            rec = _record(socket_path=str(raw.path))
            assert _probe_once(rec) is None
        finally:
            raw.close()

    def test_probe_rejects_mismatched_peer_id(self, tmp_path):
        from agent_peer.codec import encode_envelope, encode_frame
        from agent_peer.discovery import _probe_once
        from agent_peer.models import Kind, PeerIdentity, make_envelope

        rec = _record(socket_path=str(tmp_path / "unused.sock"))
        env = make_envelope(
            sender=PeerIdentity(peer_id=str(uuid.uuid4()), name="x", profile=""),
            recipient_peer_id=str(uuid.uuid4()),
            kind=Kind.ALIVE,
            content=json.dumps(
                {
                    "nonce": "n",
                    "peer_id": str(uuid.uuid4()),  # mismatched
                    "instance_id": rec.instance_id,
                    "protocol": "agent-peer/1",
                }
            ),
            conversation_id="n",
        )
        payload = encode_frame(encode_envelope(env))
        raw = _RawSock(tmp_path, reply=payload)
        try:
            assert _probe_once(rec) is None
        finally:
            raw.close()

    def test_probe_timeout(self, tmp_path):
        from agent_peer.discovery import _probe_once

        raw = _RawSock(tmp_path, reply=None, delay=2.0)  # accepts, never replies
        try:
            rec = _record(socket_path=str(raw.path))
            started = time.monotonic()
            assert _probe_once(rec) is None
            assert time.monotonic() - started < 5  # bounded
        finally:
            raw.close()


class TestResolveErrorBranches:
    def test_resolve_empty_target(self, tmp_path):
        from agent_peer.discovery import DiscoveryService

        svc = DiscoveryService(RuntimePaths(tmp_path / "runtime"))
        found, err = svc.resolve_peer("")
        assert found is None and err is not None

    def test_resolve_tilde_no_match(self, tmp_path):
        from agent_peer.discovery import DiscoveryService

        svc = DiscoveryService(RuntimePaths(tmp_path / "runtime"))
        found, err = svc.resolve_peer("name~00000000")
        assert found is None and err is not None
