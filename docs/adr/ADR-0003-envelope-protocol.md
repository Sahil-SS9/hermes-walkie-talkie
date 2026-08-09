# ADR-0003 — Envelope v1, receipts, limits and duplicate semantics

- Status: Accepted (P0 architecture freeze, 9 August 2026)
- Related: plan §4.3, §4.4, §4.5

## Context

Peers need a deterministic, versioned, bounded wire protocol that works
independently of Hermes. Delivery state must be explicit to the sender, and
duplicate or looping traffic must be impossible to deliver twice or amplify.

## Decision

### Envelope v1 (`agent-peer/1`)

Required fields:

```json
{
  "protocol": "agent-peer/1",
  "message_id": "uuid",
  "created_at": "RFC3339 UTC",
  "expires_at": "RFC3339 UTC",
  "sender": {"peer_id": "uuid", "name": "...", "profile": "..."},
  "recipient_peer_id": "uuid",
  "kind": "message",
  "content": "text",
  "reply_to": null,
  "conversation_id": null,
  "hop_count": 0
}
```

Allowed `kind` values: `ping`, `pong`, `message`, `receipt`.

Transport: length-prefixed JSON over `AF_UNIX` + `SOCK_STREAM`. The frame
length prefix is validated before allocation; oversized frames are rejected
before buffering beyond the hard ceiling.

### Receipts

Immediate receipt states: `queued`, `held`, `refused`, `unreachable`,
`expired`, `invalid`, `rate_limited`, `over_capacity`.

- A receipt is a transport-level acknowledgement; it never implies the
  recipient completed any work.
- `queued` is returned only after the host accepted delivery.
- The sender's tool returns the receipt text verbatim.

### Limits and defaults (all configurable within hard ceilings)

- Content: 32 KiB UTF-8 maximum. Full framed envelope: 64 KiB maximum.
- Default message TTL: 5 minutes. Connect timeout: 1 s. Receipt timeout: 3 s.
- Heartbeat interval: 15 s; stale threshold: 45 s, followed by a socket
  handshake before removal.
- Maximum hop count: 4. Rate limit: burst 5, sustained 20 messages/minute
  per sender/recipient pair. Pending inbox capacity: 100 messages per peer.
- Default inbound policy: `accept`.
- Invalid values fail configuration validation.

### Duplicate and loop semantics

- A `message_id` is stored/delivered at most once; duplicates return the
  prior receipt.
- Replies carry `reply_to`; no automatic ping-pong: a reply is only sent by
  explicit agent action. `conversation_id` is preserved across replies.
- Hop count increments on any forward; messages at the cap are rejected with
  `invalid`/`expired` semantics and never reach the harness.

### Security properties

- JSON only; no executable object deserialisation (no `pickle`, no
  `__class__` handling).
- Same-UID checks (Linux `SO_PEERCRED`, macOS owner credential equivalent);
  different-UID peers are refused.
- Runtime dirs `0700`, registry/sockets/DB owner-only; symlinked or
  wrong-owner paths refused.
- Canonical JSON serialisation for stable tests, logs and hashing.

## Consequences

- Senders always learn the precise delivery state.
- Memory is bounded per frame; floods are rate-limited and capacity-capped.
- Duplicates and loops are structurally impossible to amplify.
- The protocol is harness-neutral: any future adapter speaks the same wire
  format.
