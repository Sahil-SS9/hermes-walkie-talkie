"""Safe peer delivery into Hermes (HP-706, HP-707).

Inbound peer text is wrapped in an explicit ``<peer_message>`` boundary that
names the sender, peer ID and message ID, then delivered through the PUBLIC
``ctx.inject_message(..., mode="queue", target_session=...)`` seam.

Guarantees:
- Peer text is conversational input only — it cannot invoke slash commands,
  approve tools or answer protected prompts (host seam enforces this).
- The recipient model always sees WHO sent the message and that it is
  untrusted peer input, never human authorisation.
- Delivery to unknown/closed targets fails closed (False).
- Duplicate message IDs are delivered once (store dedup).
"""

from __future__ import annotations

import logging

from agent_peer.models import Envelope, ReceiptState
from agent_peer.store import MessageStore

from .config import PeerConfig
from .plugin import host_seam_supported

logger = logging.getLogger("hermes_peer.delivery")

PEER_BOUNDARY_OPEN = "<peer_message>"
PEER_BOUNDARY_CLOSE = "</peer_message>"
REQUEST_BOUNDARY_OPEN = "<peer_request>"
REQUEST_BOUNDARY_CLOSE = "</peer_request>"

_BOUNDARY_TAGS = (PEER_BOUNDARY_OPEN, PEER_BOUNDARY_CLOSE, REQUEST_BOUNDARY_OPEN, REQUEST_BOUNDARY_CLOSE)

# Each marker only needs to neutralise its OWN boundary tags in content.
# A <peer_request> inside a <peer_message> is legitimate (the request
# workflow embeds request markers as message content) and must be preserved.
_MESSAGE_TAGS = (PEER_BOUNDARY_OPEN, PEER_BOUNDARY_CLOSE)
_REQUEST_TAGS = (REQUEST_BOUNDARY_OPEN, REQUEST_BOUNDARY_CLOSE)


def _sanitise_name(name: str) -> str:
    """Strip newlines and boundary tags from a header field (SEC-R2).

    Newlines would allow header injection; boundary tags could break the
    untrusted boundary. Both are removed, not rejected, so the marker
    is always well-formed.
    """
    cleaned = name.replace("\r", "").replace("\n", "")
    for tag in _BOUNDARY_TAGS:
        cleaned = cleaned.replace(tag, "")
    return cleaned


def _escape_content(content: str, tags: tuple[str, ...]) -> str:
    """Neutralise boundary tags inside peer content (SEC-R2).

    The content is inserted between the open and close tags. If the content
    itself contains a closing tag, the text after it would appear outside
    the untrusted boundary. We neutralise the relevant boundary tags by
    inserting a zero-width space so the host model sees them as inert text.

    Only the tags belonging to the wrapping marker are neutralised — a
    ``<peer_request>`` inside a ``<peer_message>`` is legitimate (the
    request workflow embeds request markers as message content).
    """
    result = content
    for tag in tags:
        result = result.replace(tag, tag[:1] + "\u200b" + tag[1:])
    return result


def peer_message_marker(content: str, *, sender_name: str, sender_peer_id: str, message_id: str) -> str:
    """Wrap peer text in the untrusted-message boundary (SEC-1006, SEC-R2)."""
    safe_name = _sanitise_name(sender_name)
    safe_content = _escape_content(content, _MESSAGE_TAGS)
    return (
        f"{PEER_BOUNDARY_OPEN}\n"
        f"From: {safe_name}\n"
        f"Peer ID: {sender_peer_id}\n"
        f"Message ID: {message_id}\n\n"
        f"{safe_content}\n"
        f"{PEER_BOUNDARY_CLOSE}"
    )


def peer_request_marker(
    content: str,
    *,
    sender_name: str,
    sender_agent_id: str,
    request_id: str,
    summary: str,
) -> str:
    """Wrap a structured request in the inert conversational boundary (P5.6, SEC-R2).

    The recipient sees the request as untrusted peer input — it cannot
    invoke slash commands, approve tools, answer confirmation prompts or
    bypass policy (G4.9). The request_id and state are explicit so the
    recipient can act through tools/commands.
    """
    safe_name = _sanitise_name(sender_name)
    safe_content = _escape_content(content, _REQUEST_TAGS)
    safe_summary = _escape_content(summary, _REQUEST_TAGS)
    return (
        f"{REQUEST_BOUNDARY_OPEN}\n"
        f"From: {safe_name}\n"
        f"Sender Agent ID: {sender_agent_id}\n"
        f"Request ID: {request_id}\n"
        f"Summary: {safe_summary}\n\n"
        f"{safe_content}\n"
        f"{REQUEST_BOUNDARY_CLOSE}"
    )


class DeliveryAdapter:
    """Delivers inbound envelopes to the exact Hermes host session."""

    def __init__(self, ctx, session_manager, config: PeerConfig | None = None) -> None:
        self._ctx = ctx
        self._session_manager = session_manager
        self._config = config or PeerConfig()

    def deliver(self, envelope: Envelope, *, force: bool = False) -> bool:
        """Forward one inbound envelope to its target session. Returns True
        when the host accepted delivery (queued).

        ``force=True`` bypasses the dedup guard — used by explicit release
        of an already-stored held message (HP-803).
        """
        if not host_seam_supported(self._ctx):
            return False
        recipient = self._session_manager.resolve_peer(envelope.recipient_peer_id)
        if recipient is None or not recipient.host_target:
            logger.warning(
                "hermes-peer: dropping message %s for unknown peer %s",
                envelope.message_id, envelope.recipient_peer_id,
            )
            return False

        # Deduplicate: the same message_id is delivered at most once —
        # unless this is an explicit release of a stored held message.
        store: MessageStore = self._session_manager._store
        existing = store.get(envelope.message_id)
        if existing is not None and not force:
            return False
        if existing is None:
            store.record(
                {
                    "message_id": envelope.message_id,
                    "recipient_peer_id": envelope.recipient_peer_id,
                    "sender_peer_id": envelope.sender.peer_id,
                    "kind": envelope.kind.value,
                    "content": envelope.content,
                    "state": ReceiptState.QUEUED.value,
                    "created_at": envelope.created_at.isoformat(),
                    "expires_at": envelope.expires_at.isoformat(),
                    "reply_to": envelope.reply_to,
                    "conversation_id": envelope.conversation_id,
                    "delivered_at": None,
                    "hop_count": envelope.hop_count,
                }
            )

        wrapped = peer_message_marker(
            envelope.content,
            sender_name=envelope.sender.name or "unknown",
            sender_peer_id=envelope.sender.peer_id,
            message_id=envelope.message_id,
        )
        try:
            accepted = bool(
                self._ctx.inject_message(
                    wrapped,
                    role="user",
                    mode="queue",
                    target_session=recipient.host_target,
                )
            )
        except Exception as exc:  # noqa: BLE001 - fail closed
            logger.warning("hermes-peer: inject_message raised: %s", exc)
            accepted = False
        if not accepted:
            store.transition(envelope.message_id, ReceiptState.HELD)
        elif existing is not None:
            # Explicit release of a stored held message -> queued.
            store.transition(envelope.message_id, ReceiptState.QUEUED)
        return accepted
