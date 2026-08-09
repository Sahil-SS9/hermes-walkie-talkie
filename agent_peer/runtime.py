"""Per-process peer supervisor: one selector thread, many per-session sockets (ADR-0001, AP-501..AP-512).

Design:
- :class:`PeerRuntimeManager` is process-global; it owns ONE daemon thread
  running a ``selectors.DefaultSelector`` loop. The first peer registration
  starts it; the last teardown stops it.
- Each registered peer binds its own ``AF_UNIX`` stream socket in the shared
  owner-local runtime root and is served by the same selector thread
  (no thread per session).
- Connections are verified same-UID (``SO_PEERCRED``); wrong-UID peers are
  dropped.
- A stalled client only ever blocks its own buffer: sockets are
  non-blocking, reads are incremental, replies are queued per connection and
  written when the socket is writable.
- A raising delivery handler is contained per connection; the supervisor
  stays available.
- Teardown unregisters the selector entry, closes the socket, unlinks the
  EXACT owned path and removes the registry file. Crash recovery reclaims
  stale socket files on start (verified by failed connect/instance match).
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import selectors
import socket
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .codec import FrameDecoder, encode_envelope
from .constants import RECEIPT_TIMEOUT
from .errors import AgentPeerError, FrameError, TimeoutError_, UnreachableError
from .models import Envelope, Kind, PeerRecord, Receipt, ReceiptState
from .paths import RuntimePaths, select_runtime_dir
from .registry import Registry
from .transport import PeerClient, peer_credentials, verify_peer_credentials

logger = logging.getLogger("agent_peer.runtime")

MessageHandler = Callable[[Envelope], ReceiptState | str]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PeerHandle:
    """Handle returned by ``register_peer``; close() tears the peer down."""

    peer_id: str
    socket_path: Path
    _manager: PeerRuntimeManager = None  # type: ignore[assignment]

    def close(self) -> None:
        self._manager.unregister_peer(self.peer_id)


class _Connection:
    """Per-connection selector state."""

    __slots__ = ("sock", "decoder", "out_buffer", "peer_id", "closed")

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.decoder = FrameDecoder()
        self.out_buffer = bytearray()
        self.peer_id: str | None = None
        self.closed = False


class PeerRuntimeManager:
    """Process-global supervisor for peer sockets."""

    _instance: PeerRuntimeManager | None = None
    _instance_lock = threading.Lock()

    def __init__(self, runtime_root: Path | RuntimePaths | None = None, registry: Registry | None = None) -> None:
        self._paths = (
            runtime_root
            if isinstance(runtime_root, RuntimePaths)
            else RuntimePaths(runtime_root or select_runtime_dir())
        )
        self._registry = registry or Registry(self._paths)
        self._selector = selectors.DefaultSelector()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._peers: dict[str, PeerRecord] = {}
        self._connections: dict[socket.socket, _Connection] = {}
        self._handlers: dict[str, MessageHandler] = {}
        self._lock = threading.RLock()
        self._wakeup_r, self._wakeup_w = os.pipe()
        self._selector.register(self._wakeup_r, selectors.EVENT_READ, "wakeup")

    # ------------------------------------------------------------------
    # Process-global access
    # ------------------------------------------------------------------

    @classmethod
    def get(cls) -> PeerRuntimeManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
                atexit.register(cls._instance.shutdown)
            return cls._instance

    # ------------------------------------------------------------------
    # Peer lifecycle
    # ------------------------------------------------------------------

    def register_peer(self, record: PeerRecord, on_message: MessageHandler) -> PeerHandle:
        """Register a peer: bind its socket, start the supervisor if needed."""
        with self._lock:
            socket_path = self._paths.socket_path_for(record.peer_id)
            self._reclaim_stale_socket(socket_path)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(socket_path))
            sock.listen(64)
            sock.setblocking(False)
            self._selector.register(sock, selectors.EVENT_READ, "listen")
            import dataclasses

            record = dataclasses.replace(record, socket_path=str(socket_path))
            self._peers[record.peer_id] = record
            self._handlers[record.peer_id] = on_message
            self._registry.register(record)
            self._ensure_thread()
            handle = PeerHandle(peer_id=record.peer_id, socket_path=socket_path, _manager=self)
            return handle

    def unregister_peer(self, peer_id: str) -> None:
        """Graceful teardown: selector, socket, exact path, registry file."""
        with self._lock:
            record = self._peers.pop(peer_id, None)
            self._handlers.pop(peer_id, None)
            if record is not None:
                with suppress(Exception):
                    self._registry.update_presence(peer_id, "closing")
            socket_path = self._paths.socket_path_for(peer_id)
            self._unbind_socket(socket_path)
            self._registry.unregister(peer_id)
            if not self._peers:
                self._stop_event.set()
                self._wakeup()
                self._join_thread()

    def send(self, envelope: Envelope) -> Receipt:
        """Send one envelope to its recipient peer and return the receipt.

        Resolves the recipient's registry record, connects to its socket,
        awaits the transport receipt (bounded) and maps failures to explicit
        receipt states.
        """
        recipient = self._registry.get(envelope.recipient_peer_id)
        if recipient is None or not recipient.socket_path:
            return self._receipt(envelope, ReceiptState.UNREACHABLE, "no registry record")
        try:
            client = PeerClient(recipient.socket_path, receipt_timeout=RECEIPT_TIMEOUT)
            reply = client.request(envelope)
        except UnreachableError as exc:
            return self._receipt(envelope, ReceiptState.UNREACHABLE, str(exc))
        except TimeoutError_ as exc:
            return self._receipt(envelope, ReceiptState.UNREACHABLE, f"timeout: {exc}")
        except (FrameError, AgentPeerError) as exc:
            return self._receipt(envelope, ReceiptState.INVALID, str(exc))
        if reply.kind is Kind.RECEIPT:
            try:
                return Receipt(
                    message_id=envelope.message_id,
                    state=ReceiptState(reply.content),
                    recipient_peer_id=envelope.recipient_peer_id,
                    detail=f"reply: {reply.content}",
                    delivered_at=_now_iso(),
                )
            except ValueError:
                return self._receipt(envelope, ReceiptState.INVALID, f"bad receipt {reply.content!r}")
        if reply.kind is Kind.PONG:
            return self._receipt(envelope, ReceiptState.QUEUED, "pong")
        return self._receipt(envelope, ReceiptState.INVALID, f"unexpected reply kind {reply.kind.value}")

    def shutdown(self) -> None:
        """Stop the supervisor and tear down every peer."""
        with self._lock:
            peer_ids = list(self._peers.keys())
            for peer_id in peer_ids:
                self.unregister_peer(peer_id)
            self._stop_event.set()
            self._wakeup()
            self._join_thread()
            with suppress(Exception):
                self._selector.close()

    # ------------------------------------------------------------------
    # Supervisor thread
    # ------------------------------------------------------------------

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="agent-peer-supervisor", daemon=True)
        self._thread.start()

    def _join_thread(self) -> None:
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=3)

    def _wakeup(self) -> None:
        with contextlib.suppress(OSError):
            os.write(self._wakeup_w, b"x")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                events = self._selector.select(timeout=0.5)
            except OSError:
                break
            for key, _mask in events:
                if key.data == "wakeup":
                    with contextlib.suppress(OSError):
                        os.read(self._wakeup_r, 64)
                    continue
                if key.data == "listen":
                    self._accept(key.fileobj)  # type: ignore[arg-type]
                    continue
                self._service_connection(key.fileobj)  # type: ignore[arg-type]
            self._service_writable()
            if not self._peers and not self._stop_event.is_set():
                # Nothing registered: idle until a wakeup re-checks.
                self._stop_event.set()
                self._wakeup()

    def _accept(self, listen_sock: socket.socket) -> None:
        try:
            conn, _ = listen_sock.accept()
        except OSError:
            return
        conn.setblocking(False)
        if not verify_peer_credentials(peer_credentials(conn)):
            logger.warning("dropping connection from foreign UID")
            with contextlib.suppress(OSError):
                conn.close()
            return
        self._connections[conn] = _Connection(conn)
        self._selector.register(conn, selectors.EVENT_READ, "conn")

    def _service_connection(self, conn: socket.socket) -> None:
        state = self._connections.get(conn)
        if state is None or state.closed:
            return
        try:
            chunk = conn.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            self._drop_connection(conn)
            return
        if not chunk:
            self._drop_connection(conn)
            return
        try:
            for envelope in state.decoder.feed(chunk):
                self._dispatch(conn, state, envelope)
        except FrameError as exc:
            logger.warning("dropping malformed frame: %s", exc)
            self._reply(conn, state, "invalid", str(exc))
            self._drop_connection(conn)

    def _dispatch(self, conn: socket.socket, state: _Connection, envelope: Envelope) -> None:
        if envelope.kind is Kind.PING:
            self._reply(conn, state, "pong")
            return
        handler = self._handlers.get(envelope.recipient_peer_id)
        if handler is None:
            self._reply(conn, state, ReceiptState.UNREACHABLE.value, "no such peer here")
            return
        try:
            outcome = handler(envelope)
        except Exception as exc:  # noqa: BLE001 - contained per connection
            logger.warning("peer handler raised for %s: %s", envelope.message_id, exc)
            self._reply(conn, state, ReceiptState.INVALID.value, "handler error")
            return
        state_name = outcome.value if isinstance(outcome, ReceiptState) else str(outcome)
        if state_name not in {s.value for s in ReceiptState}:
            state_name = ReceiptState.INVALID.value
        self._reply(conn, state, state_name)

    def _reply(self, conn: socket.socket, state: _Connection, content: str, detail: str = "") -> None:
        from .models import PeerIdentity, make_envelope

        zero = "00000000-0000-0000-0000-000000000000"
        sender = state.peer_id or zero
        reply = make_envelope(
            sender=PeerIdentity(peer_id=zero, name="agent-peer", profile=""),
            recipient_peer_id=sender,
            kind=Kind.PONG if content == "pong" else Kind.RECEIPT,
            content=content,
        )
        try:
            from .codec import encode_frame

            state.out_buffer.extend(encode_frame(encode_envelope(reply)))
            self._flush(conn, state)
        except Exception:  # noqa: BLE001
            self._drop_connection(conn)

    def _flush(self, conn: socket.socket, state: _Connection) -> None:
        while state.out_buffer:
            try:
                sent = conn.send(state.out_buffer)
            except BlockingIOError:
                self._selector.modify(conn, selectors.EVENT_READ | selectors.EVENT_WRITE, "conn")
                return
            except OSError:
                self._drop_connection(conn)
                return
            del state.out_buffer[:sent]
        self._selector.modify(conn, selectors.EVENT_READ, "conn")

    def _service_writable(self) -> None:
        for key in list(self._selector.get_map().values()):
            if key.data != "conn":
                continue
            conn = key.fileobj
            state = self._connections.get(conn)  # type: ignore[arg-type]
            if state is None or state.closed:
                continue
            if state.out_buffer and key.events & selectors.EVENT_WRITE:
                self._flush(conn, state)  # type: ignore[arg-type]

    def _drop_connection(self, conn: socket.socket) -> None:
        state = self._connections.pop(conn, None)
        if state is None or state.closed:
            return
        state.closed = True
        with suppress(Exception):
            self._selector.unregister(conn)
        with contextlib.suppress(OSError):
            conn.close()

    def _unbind_socket(self, socket_path: Path) -> None:
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("could not unlink socket %s", socket_path)

    def _reclaim_stale_socket(self, socket_path: Path) -> None:
        """Crash recovery: remove a stale socket only if nothing listens on it."""
        if not socket_path.exists():
            return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect(str(socket_path))
            # Something IS listening; do not reclaim (another live instance).
            probe.close()
            return
        except OSError:
            probe.close()
            self._unbind_socket(socket_path)

    def _receipt(self, envelope: Envelope, state: ReceiptState, detail: str) -> Receipt:
        return Receipt(
            message_id=envelope.message_id,
            state=state,
            recipient_peer_id=envelope.recipient_peer_id,
            detail=detail,
            delivered_at=_now_iso(),
        )
