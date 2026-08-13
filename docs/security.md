# Security model

Peer messaging is a new trust boundary. This document states the threat
model, the enforced controls and the non-goals for V1/V1.1.

## Same-user boundary

- All runtime/state paths are owner-only (`0700` dirs, `0600` files) and
  shared only under one OS user.
- Linux connections are verified same-UID via `SO_PEERCRED`; wrong-UID peers
  are dropped. On platforms without `SO_PEERCRED` (macOS), the owner-verified
  runtime directory is the boundary. Windows uses SID-bound DACLs
  (owner-only; wrong-user denied at the OS boundary).
- Symlinked or wrong-owner runtime paths are refused, including the XDG root
  itself and intermediate directories created under permissive umasks.
- The registry never trusts a PID alone: identity requires the matching
  `instance_id` (socket handshake). Stale entries are removed only after
  expiry **and** a failed handshake — never while another live instance's
  files could be affected.
- `agent_id` is a stable per-profile UUID persisted owner-only under
  HERMES_HOME; it is never inferred from alias or path text (G2.3).

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
- Requests arrive as inert `<peer_request>` conversational text — never a
  host command; cancellation is advisory with no interrupt seam and no
  command authority (G4.6, `test_request_inert_control.py`).
- Broadcast fan-out is bounded (hard ceiling 64) and child IDs are
  deterministic; concurrent duplicate broadcasters converge on exactly one
  child per recipient (atomic `created→in_flight` gate).
- Desktop plugin install is explicit only (G6.9): plugin load never writes
  to HERMES_HOME; `hermes peer desktop install` is the sole installer.

## Liveness probe boundary

- Discovery probes use the DISCOVER/ALIVE challenge-response over the same
  `AF_UNIX` framed transport. The nonce is generated with `secrets`, is
  single-use per probe, and every identity field (peer, instance, session,
  protocol) is compared exactly. A malformed, mismatched, duplicated or
  ambiguous authority fails closed and is never listed or routed to.
- Same-UID `SO_PEERCRED` checks remain mandatory on accepted connections.
- PID is diagnostic only and never establishes liveness.

## Terminal-control caveat

The inert-control guarantee covers command, approval, shell and file-drop
dispatch: peer text is conversational input only. It does NOT guarantee that
terminal escape sequences are inert on TUI surfaces — an injected payload
containing control characters is delivered verbatim inside the
`<peer_message>` boundary, so a TUI renderer that interprets escapes could
still display them. Peer text must therefore be treated as untrusted display
input on any surface that renders raw control characters. See the review
packet's DEVIATIONS.md for the exact scope.

## Bounded resources

- Content ≤ 32 KiB; framed envelope ≤ 64 KiB; the length prefix is validated
  before payload buffering.
- Rate limit: burst 5 / 20 per minute per sender-recipient pair.
- Pending inbox capacity: 100 per peer.
- TTL 5 minutes; hop cap 4; duplicate message IDs deliver once.
- Retention cleanup is batched and never blocks active delivery.
- Group member cap: default 32, hard 128.
- Broadcast fan-out concurrency: default 8, hard 64.
- Metrics/events are content-free by structural gate: no message body ever
  reaches metrics or the event stream.
- Event broker clients capped (default 256); slow consumers are dropped, the
  broker stays available.

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

## Non-goals (V1/V1.1)

- No cross-machine networking, no encryption in transit (same-user local
  sockets only), no authentication beyond the OS-user boundary, no file
  transfer, no remote execution. Any future remote transport must be
  a separate adapter with explicit authentication/encryption, off by default.
- No nested groups (membership is a flat agent_id set).
- Cancellation is advisory — no interrupt seam exists by design.
- Native Windows CI verifies named-pipe transport and the SID/DACL owner
  boundary. A Windows wheel-install smoke and full Desktop/Electron
  interaction remain separate follow-up coverage.
