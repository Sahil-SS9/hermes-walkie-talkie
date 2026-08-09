# Security model

Peer messaging is a new trust boundary. This document states the threat
model, the enforced controls and the non-goals for v1.

## Same-user boundary

- All runtime/state paths are owner-only (`0700` dirs, `0600` files) and
  shared only under one OS user.
- Linux connections are verified same-UID via `SO_PEERCRED`; wrong-UID peers
  are dropped. On platforms without `SO_PEERCRED` (macOS), the owner-verified
  runtime directory is the boundary.
- Symlinked or wrong-owner runtime paths are refused, including the XDG root
  itself and intermediate directories created under permissive umasks.
- The registry never trusts a PID alone: identity requires the matching
  `instance_id` (socket handshake). Stale entries are removed only after
  expiry **and** a failed handshake — never while another live instance's
  files could be affected.

## Untrusted peer input

- Inbound text is wrapped in `<peer_message>` with the sender name, peer ID
  and message ID — the recipient model always knows the sender and that the
  input is not human authorisation.
- Injected text is conversational input only. The host seam guarantees it
  cannot invoke slash commands, approve tools, run shell lines or answer
  protected confirmation/clarification prompts (CLI conversational queue +
  gateway `non_control` gate; verified by the inert-control tests).
- A peer message never carries executable payloads: JSON only, no
  deserialisation of objects (no pickle, no `__class__` handling).

## Bounded resources

- Content ≤ 32 KiB; framed envelope ≤ 64 KiB; the length prefix is validated
  before payload buffering.
- Rate limit: burst 5 / 20 per minute per sender-recipient pair.
- Pending inbox capacity: 100 per peer.
- TTL 5 minutes; hop cap 4; duplicate message IDs deliver once.
- Retention cleanup is batched and never blocks active delivery.

## Failure modes are observable

- Malformed, truncated, oversized, unknown-version or arbitrary byte input
  is rejected per-connection; the supervisor stays available (fuzzed).
- Disk-full / read-only store failures raise observable errors; existing
  state is never corrupted (WAL + transactions).
- Every rejection produces an explicit receipt state
  (`refused`, `rate_limited`, `over_capacity`, `expired`, `invalid`,
  `unreachable`) — no silent drops when a receipt is possible.

## No-network guarantee

- The feature opens Unix-domain sockets only. No TCP listener exists in any
  supported configuration (static source audit + per-process `/proc` inode
  verification in tests).

## Logging

- Logs carry message IDs, sender IDs, sizes and outcomes — never raw message
  bodies (static audit + review).

## Non-goals (v1)

- No cross-machine networking, no encryption in transit (same-user local
  sockets only), no authentication beyond the OS-user boundary, no broadcast,
  no file transfer, no remote execution. Any future remote transport must be
  a separate adapter with explicit authentication/encryption, off by default.
