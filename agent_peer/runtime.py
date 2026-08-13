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

from .codec import FrameDecoder, decode_envelope, encode_envelope
from .constants import PROTOCOL_ID, RECEIPT_TIMEOUT
from .errors import AgentPeerError, FrameError, TimeoutError_, UnreachableError
from .models import Envelope, Kind, PeerRecord, Receipt, ReceiptState
from .paths import RuntimePaths, select_runtime_dir
from .registry import Registry

logger = logging.getLogger("agent_peer.runtime")

MessageHandler = Callable[[Envelope], ReceiptState | str]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PeerHandle:
    """Handle returned by ``register_peer``; close() tears the peer down.

    ``record`` is the canonical BOUND record (with socket_path, socket_uid,
    socket_inode populated) that was atomically published — callers must
    store THIS record, never the pre-bind copy (F-02, REM-203).
    """

    peer_id: str
    socket_path: Path
    record: PeerRecord | None = None
    _manager: PeerRuntimeManager = None  # type: ignore[assignment]

    def close(self) -> None:
        self._manager.unregister_peer(self.peer_id)


class _Connection:
    """Per-connection selector state."""

    __slots__ = ("sock", "decoder", "out_buffer", "peer_id", "listener_peer_id", "closed")

    def __init__(self, sock: socket.socket, listener_peer_id: str) -> None:
        self.sock = sock
        self.decoder = FrameDecoder()
        self.out_buffer = bytearray()
        self.peer_id: str | None = None
        self.listener_peer_id = listener_peer_id
        self.closed = False


class PeerRuntimeManager:
    """Process-global supervisor for peer sockets."""

    _instance: PeerRuntimeManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        runtime_root: Path | RuntimePaths | None = None,
        registry: Registry | None = None,
        backend=None,
        path_backend=None,
    ) -> None:
        from .backends import get_transport_backend
        from .platform_paths import get_path_backend

        self._paths = (
            runtime_root
            if isinstance(runtime_root, RuntimePaths)
            else RuntimePaths(runtime_root or select_runtime_dir())
        )
        self._registry = registry or Registry(self._paths)
        self._backend = backend or get_transport_backend()
        self._path_backend = path_backend or get_path_backend()
        self._selector = selectors.DefaultSelector()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._peers: dict[str, PeerRecord] = {}
        self._connections: dict[socket.socket, _Connection] = {}
        self._handlers: dict[str, MessageHandler] = {}
        # peer_id -> listening handle (exact ownership, REM-405).
        self._listeners: dict[str, object] = {}
        self._listener_owners: dict[object, str] = {}
        self._lock = threading.RLock()
        # Windows: named pipes have no pollable fd, so the supervisor runs a
        # bounded per-listener wait thread per peer (P2 native gate) instead
        # of the POSIX selector. Keyed by peer_id for teardown.
        self._is_windows = os.name != "posix"
        self._windows_threads: dict[str, threading.Thread] = {}
        # Use socketpair for wakeup — works with selectors on ALL platforms.
        # os.pipe() FDs are not selectable on Windows where SelectSelector
        # only supports sockets, causing silent failures if the selector
        # loop is ever invoked.
        self._wakeup_r, self._wakeup_w = socket.socketpair()
        self._wakeup_r.setblocking(False)
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
        """Register a peer: bind its socket, capture UID/inode, start the
        supervisor, then atomically publish the canonical bound record.

        Registration order (REM-106): mint IDs -> derive socket path -> bind
        -> set owner permissions -> capture UID/inode from the bound socket ->
        register the listener -> start/confirm the supervisor -> publish the
        complete canonical record. On any failure before publication, the
        listener is closed/unregistered and no registry record remains.
        """
        with self._lock:
            socket_path = self._paths.socket_path_for(record.peer_id, record.instance_id)
            self._reclaim_stale_socket(socket_path)
            listener = None
            try:
                listener = self._backend.bind_listener(
                    socket_path,
                    instance_id=record.instance_id,
                )
                # Capture the bound socket's UID and inode (REM-105/106).
                # POSIX: AF_UNIX socket files expose st_uid/st_ino and the
                # discovery fence compares them. Windows: named pipes have
                # no filesystem node (SID/DACL is the authority), so the
                # stat cannot apply — leave the authority fields unset.
                socket_uid: int | None = None
                socket_inode: int | None = None
                if os.name == "posix":
                    try:
                        st = socket_path.stat()
                        socket_uid = st.st_uid
                        socket_inode = st.st_ino
                    except OSError:
                        socket_uid = None
                        socket_inode = None
                import dataclasses

                record = dataclasses.replace(
                    record,
                    socket_path=str(socket_path),
                    socket_uid=socket_uid,
                    socket_inode=socket_inode,
                    protocol=record.protocol or PROTOCOL_ID,
                )
                if self._is_windows:
                    # Named pipes: bounded per-listener wait thread (P2).
                    self._start_windows_listener(record.peer_id, listener)
                    self._thread = None  # selector thread unused on Windows
                else:
                    self._selector.register(listener, selectors.EVENT_READ, "listen")
                self._peers[record.peer_id] = record
                self._handlers[record.peer_id] = on_message
                self._listeners[record.peer_id] = listener
                self._listener_owners[listener] = record.peer_id
                if not self._is_windows:
                    self._ensure_thread()
                    if self._thread is None or not self._thread.is_alive():
                        raise RuntimeError("peer supervisor failed to start")
                # Publication is the final registration step: the listener and
                # confirmed supervisor are already ready to answer probes.
                self._registry.register(record)
                handle = PeerHandle(
                    peer_id=record.peer_id,
                    socket_path=socket_path,
                    record=record,
                    _manager=self,
                )
                return handle
            except Exception:
                # Close/unregister the listener and leave no record.
                if listener is not None:
                    if not self._is_windows:
                        with suppress(Exception):
                            self._selector.unregister(listener)
                    # On Windows, close the pipe handle FIRST so the
                    # pending ConnectNamedPipe in the wait thread returns
                    # immediately, THEN join the thread.
                    if self._is_windows:
                        with suppress(Exception):
                            listener.close()
                        self._stop_windows_listener(record.peer_id)
                    else:
                        self._stop_windows_listener(record.peer_id)
                        listener.close()
                self._peers.pop(record.peer_id, None)
                self._handlers.pop(record.peer_id, None)
                owned_listener = self._listeners.pop(record.peer_id, None)
                if owned_listener is not None:
                    self._listener_owners.pop(owned_listener, None)
                self._registry.unregister_if_current(
                    record.peer_id,
                    expected_instance_id=record.instance_id,
                    expected_socket_path=record.socket_path,
                    expected_socket_uid=record.socket_uid,
                    expected_socket_inode=record.socket_inode,
                )
                if not self._peers:
                    self._stop_event.set()
                    self._wakeup()
                    self._join_thread()
                raise

    def update_record(self, record: PeerRecord) -> bool:
        """Refresh mutable in-memory metadata behind bound authority."""
        with self._lock:
            current = self._peers.get(record.peer_id)
            if current is None:
                return False
            if (
                current.instance_id,
                current.socket_path,
                current.socket_uid,
                current.socket_inode,
            ) != (
                record.instance_id,
                record.socket_path,
                record.socket_uid,
                record.socket_inode,
            ):
                return False
            self._peers[record.peer_id] = record
            return True

    def unregister_peer(self, peer_id: str) -> None:
        """Graceful teardown (REM-406, §4.7 order):

        1. mark exact peer closing when its record still matches;
        2. unregister exact listener FD from selector;
        3. close exact listener FD;
        4. close/unregister accepted connections belonging to that
           listener/peer;
        5. compare socket UID/inode with the canonical record;
        6. unlink exact owned socket;
        7. remove exact matching registry record;
        8. stop the supervisor only after the last peer is gone;
        9. close wakeup pipe FDs and selector exactly once on final shutdown.

        A path is never unlinked while an untracked live listener remains
        bound to it (NG-07).
        """
        with self._lock:
            record = self._peers.pop(peer_id, None)
            self._handlers.pop(peer_id, None)
            listener = self._listeners.pop(peer_id, None)
            if record is not None:
                with suppress(Exception):
                    self._registry.update_presence(peer_id, "closing", expected=record)
            socket_path = (
                Path(record.socket_path)
                if record is not None and record.socket_path
                else self._paths.socket_path_for(peer_id)
            )

            # 2+3. Unregister and close the exact listener FD. The endpoint
            # path is NOT touched here — step 6 unlinks only after the
            # UID/inode fence proves the path is still the exact owned one.
            if listener is not None:
                self._listener_owners.pop(listener, None)
                if not self._is_windows:
                    with suppress(Exception):
                        self._selector.unregister(listener)  # type: ignore[attr-defined]
                # On Windows, close the pipe handle FIRST to unblock the
                # pending synchronous ConnectNamedPipe in the wait thread.
                # CloseHandle on a handle with a pending synchronous pipe
                # operation may raise — suppress so the thread join still runs.
                if self._is_windows:
                    with suppress(Exception):
                        listener.close_fd()  # type: ignore[attr-defined]
                    self._stop_windows_listener(peer_id)
                else:
                    listener.close_fd()  # type: ignore[attr-defined]
                    self._stop_windows_listener(peer_id)

            # 4. Close accepted connections belonging to this listener/peer.
            for conn in list(self._connections.keys()):
                state = self._connections.get(conn)
                if state is not None and state.listener_peer_id == peer_id:
                    self._drop_connection(conn)

            # 5+6. Compare socket UID/inode with the canonical record, then
            # unlink ONLY the exact owned socket (never a replacement).
            if record is not None and record.socket_path:
                try:
                    st = socket_path.stat()
                    if st.st_uid == record.socket_uid and st.st_ino == record.socket_inode:
                        self._unbind_socket(socket_path)
                    else:
                        logger.warning(
                            "hermes-peer: teardown refused to unlink replaced socket %s "
                            "(uid/inode mismatch) for %s",
                            socket_path, peer_id,
                        )
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.warning("could not stat socket %s", socket_path)

            # 7. Remove the exact registry record.
            if record is not None:
                self._registry.unregister_if_current(
                    peer_id,
                    expected_instance_id=record.instance_id,
                    expected_socket_path=record.socket_path,
                    expected_socket_uid=record.socket_uid,
                    expected_socket_inode=record.socket_inode,
                )

            # 8. Stop the supervisor only after the last peer is gone.
            if not self._peers:
                self._stop_event.set()
                self._wakeup()
                self._join_thread()

    def send(self, envelope: Envelope) -> Receipt:
        """Send one envelope to its recipient peer and return the receipt.

        Resolves the recipient's registry record, connects to its socket,
        awaits the transport receipt (bounded) and maps failures to explicit
        receipt states.

        Sender authentication (SEC-R1): the envelope's ``sender.peer_id`` must
        match a peer registered in this runtime manager. The sender identity
        is overridden from the registered record so the recipient sees the
        authenticated identity, never a caller-claimed one. An unregistered
        sender is rejected with INVALID — no spoofing is possible.
        """
        authenticated_sender = self._authenticate_sender(envelope)
        if authenticated_sender is None:
            return self._receipt(envelope, ReceiptState.INVALID, "sender not registered in this runtime")
        envelope = self._stamp_sender(envelope, authenticated_sender)
        recipient = self._registry.get(envelope.recipient_peer_id)
        if recipient is None or not recipient.socket_path:
            return self._receipt(envelope, ReceiptState.UNREACHABLE, "no registry record")
        try:
            endpoint = self._backend_endpoint(recipient.socket_path)
            payload = encode_envelope(envelope).encode("utf-8")
            reply_payload = self._backend.request(
                endpoint, payload, timeout=RECEIPT_TIMEOUT
            )
            reply = decode_envelope(reply_payload)
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
        """Stop the supervisor and tear down every peer.

        Wakeup pipe FDs and the selector are closed exactly once on final
        shutdown (REM-406 step 9). Re-entrant shutdown is a no-op.
        """
        with self._lock:
            if getattr(self, "_shutdown_done", False):
                return
            peer_ids = list(self._peers.keys())
            for peer_id in peer_ids:
                self.unregister_peer(peer_id)
            # Stop any remaining Windows wait threads (unregister_peer
            # joins the peer's thread; this is belt-and-braces for peers
            # that were never registered via the normal path).
            for pid in list(self._windows_threads.keys()):
                self._stop_windows_listener(pid)
            self._stop_event.set()
            self._wakeup()
            self._join_thread()
            # Close wakeup sockets exactly once.
            for sock in (self._wakeup_r, self._wakeup_w):
                with contextlib.suppress(OSError):
                    sock.close()
            with suppress(Exception):
                self._selector.close()
            self._shutdown_done = True

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

    def _start_windows_listener(self, peer_id: str, listener: object) -> None:
        """Start the bounded per-listener wait thread (P2 native gate).

        Named pipes are not selectable; each listener gets one daemon
        thread that blocks on ConnectNamedPipe, verifies the client SID
        and services request/reply frames until the listener is closed.
        """
        self._stop_windows_listener(peer_id)
        t = threading.Thread(
            target=self._windows_wait_loop,
            args=(peer_id, listener),
            name=f"agent-peer-windows-{peer_id[:8]}",
            daemon=True,
        )
        self._windows_threads[peer_id] = t
        t.start()

    def _stop_windows_listener(self, peer_id: str) -> None:
        t = self._windows_threads.pop(peer_id, None)
        if t is not None:
            t.join(timeout=3)

    def _windows_wait_loop(self, peer_id: str, listener: object) -> None:
        """Serve one named-pipe listener: accept -> verify -> dispatch."""
        while not self._stop_event.is_set():
            try:
                conn = listener.accept()  # type: ignore[attr-defined]
                if conn is None:
                    continue  # accept timeout — check stop event and retry
            except Exception:
                return  # listener closed during teardown
            try:
                evidence = self._backend.verify_remote_owner(conn._pipe)
                if not evidence.authenticated:
                    logger.warning(
                        "dropping named-pipe connection from foreign owner: %s",
                        evidence.detail,
                    )
                    continue
                state = _Connection(conn, peer_id)  # type: ignore[arg-type]
                self._service_connection(conn, state)  # type: ignore[arg-type]
            except Exception:
                logger.exception("named-pipe connection error for %s", peer_id)
            finally:
                with contextlib.suppress(Exception):
                    conn.close()  # type: ignore[attr-defined]

    def _wakeup(self) -> None:
        with contextlib.suppress(OSError):
            self._wakeup_w.send(b"x")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                events = self._selector.select(timeout=0.5)
            except OSError:
                break
            for key, _mask in events:
                if key.data == "wakeup":
                    with contextlib.suppress(OSError):
                        self._wakeup_r.recv(64)
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

    def _accept(self, listen_handle: object) -> None:
        try:
            conn = listen_handle.accept()  # type: ignore[attr-defined]
        except OSError:
            return
        conn.setblocking(False)
        evidence = self._backend.verify_remote_owner(conn)
        if not evidence.authenticated:
            logger.warning("dropping connection from foreign owner: %s", evidence.detail)
            with contextlib.suppress(OSError):
                conn.close()
            return
        listener_peer_id = self._listener_owners.get(listen_handle)
        if listener_peer_id is None:
            with contextlib.suppress(OSError):
                conn.close()
            return
        self._connections[conn] = _Connection(conn, listener_peer_id)
        self._selector.register(conn, selectors.EVENT_READ, "conn")

    def _service_connection(self, conn: socket.socket, state: _Connection | None = None) -> None:
        if state is None:
            state = self._connections.get(conn)  # type: ignore[arg-type]
        if state is None or state.closed:
            return
        try:
            chunk = conn.recv(65536)  # type: ignore[attr-defined]
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
        if envelope.kind is Kind.DISCOVER:
            self._reply_alive(conn, state, envelope)
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

    def _reply_alive(self, conn: socket.socket, state: _Connection, request: Envelope) -> None:
        """Answer a DISCOVER challenge with an ALIVE envelope carrying the
        exact identity of THIS listener (REM-107).

        The ALIVE reply embeds the request's nonce (``conversation_id`` is
        used as the opaque nonce channel) so the requester can compare it
        exactly, plus peer/instance/session/protocol/status.
        """
        from .models import PeerIdentity, make_envelope

        # The DISCOVER envelope's sender identifies the requester; the
        # recipient_peer_id is the peer being probed. Nonce rides in
        # conversation_id (opaque, single-use per probe).
        nonce = request.conversation_id or ""
        record = self._peers.get(request.recipient_peer_id)
        if record is None:
            self._reply(conn, state, ReceiptState.UNREACHABLE.value, "no such peer here")
            return
        zero = "00000000-0000-0000-0000-000000000000"
        # Encode identity fields in content as canonical JSON so the
        # requester can verify them exactly.
        import json as _json

        identity = _json.dumps(
            {
                "nonce": nonce,
                "peer_id": record.peer_id,
                "instance_id": record.instance_id,
                "session_id": record.session_id,
                "agent_id": record.agent_id,
                "protocols": list(record.protocols),
                "capabilities": record.capabilities,
                "protocol": record.protocol,
                "status": record.status,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        reply = make_envelope(
            sender=PeerIdentity(peer_id=record.peer_id, name=record.name, profile=record.profile),
            recipient_peer_id=request.sender.peer_id or zero,
            kind=Kind.ALIVE,
            content=identity,
            conversation_id=nonce,
        )
        try:
            from .codec import encode_frame

            state.out_buffer.extend(encode_frame(encode_envelope(reply)))
            self._flush(conn, state)
        except Exception:  # noqa: BLE001
            self._drop_connection(conn)

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
                sent = conn.send(state.out_buffer)  # type: ignore[attr-defined]
            except BlockingIOError:
                if self._is_windows:
                    return  # pipe send is blocking; nothing to reschedule
                self._selector.modify(conn, selectors.EVENT_READ | selectors.EVENT_WRITE, "conn")
                return
            except OSError:
                self._drop_connection(conn)
                return
            del state.out_buffer[:sent]
        if not self._is_windows:
            self._selector.modify(conn, selectors.EVENT_READ, "conn")

    def _service_writable(self) -> None:
        if self._is_windows:
            return
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
        if not self._is_windows:
            with suppress(Exception):
                self._selector.unregister(conn)
        with contextlib.suppress(OSError):
            conn.close()  # type: ignore[attr-defined]

    def _unbind_socket(self, socket_path: Path) -> None:
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("could not unlink socket %s", socket_path)

    def _backend_endpoint(self, socket_path: str):
        """Wrap a recorded socket path as a backend transport endpoint."""
        from .backends.base import TransportEndpoint

        kind = "named-pipe" if self._is_windows else "unix"
        return TransportEndpoint(kind=kind, address=socket_path)

    def _reclaim_stale_socket(self, socket_path: Path) -> None:
        """Crash recovery: remove a stale socket only if nothing listens on it."""
        if not socket_path.exists():
            return
        endpoint = self._backend_endpoint(str(socket_path))
        if self._backend.bound(endpoint, timeout=0.5):
            # Something IS listening; do not reclaim (another live instance).
            return
        self._unbind_socket(socket_path)

    def _authenticate_sender(self, envelope: Envelope) -> PeerRecord | None:
        """Return the registered peer matching the envelope's sender, or None.

        SEC-R1: the sender is authenticated by matching ``sender.peer_id``
        against the peers registered in THIS runtime manager. The bound
        record (with the real name and profile) is the authenticated identity.
        """
        with self._lock:
            for record in self._peers.values():
                if record.peer_id == envelope.sender.peer_id:
                    return record
        return None

    @staticmethod
    def _stamp_sender(envelope: Envelope, record: PeerRecord) -> Envelope:
        """Override the envelope sender with the authenticated peer record."""
        import dataclasses

        from .models import PeerIdentity

        authenticated = PeerIdentity(
            peer_id=record.peer_id,
            name=record.name,
            profile=record.profile,
        )
        return dataclasses.replace(envelope, sender=authenticated)

    def _receipt(self, envelope: Envelope, state: ReceiptState, detail: str) -> Receipt:
        return Receipt(
            message_id=envelope.message_id,
            state=state,
            recipient_peer_id=envelope.recipient_peer_id,
            detail=detail,
            delivered_at=_now_iso(),
        )
