# Agent Peer protocol v1 (`agent-peer/1`)

Wire protocol for same-machine peer messaging. Versioned, bounded,
JSON-only, harness-neutral. Locked by ADR-0003.

## Transport

- Unix-domain socket, `AF_UNIX` + `SOCK_STREAM`.
- Length-prefixed frames: 4-byte big-endian unsigned length + UTF-8 JSON.
- The length prefix is validated against the hard ceiling **before** payload
  buffering; oversized frames are rejected immediately.
- Maximum content: 32 KiB. Maximum full framed envelope: 64 KiB.

## Envelope

```json
{
  "protocol": "agent-peer/1",
  "message_id": "0f9a2c1e-8b4d-4f2a-9e6b-1c2d3e4f5a6b",
  "created_at": "2026-08-09T14:30:00.123456Z",
  "expires_at": "2026-08-09T14:35:00.123456Z",
  "sender": {"peer_id": "3c1f...", "name": "architect", "profile": "default"},
  "recipient_peer_id": "7e2d...",
  "kind": "message",
  "content": "The API schema changed: tenant_id replaces account_id.",
  "reply_to": null,
  "conversation_id": null,
  "hop_count": 0
}
```

| Field | Type | Rules |
|---|---|---|
| `protocol` | string | MUST be `agent-peer/1` |
| `message_id` | UUID string | unique per message; drives deduplication |
| `created_at` | RFC3339 UTC | aware datetime |
| `expires_at` | RFC3339 UTC | after `created_at`; expiry blocks delivery |
| `sender` | object | `peer_id` (UUID), `name`, `profile` |
| `recipient_peer_id` | UUID string | exact target peer |
| `kind` | string | `ping`, `pong`, `message`, `receipt`, `discover`, `alive` |
| `content` | string | ≤ 32 KiB UTF-8 |
| `reply_to` | UUID string \| null | correlation to a prior message |
| `conversation_id` | string \| null | preserved across replies |
| `hop_count` | integer | 0..4; cap prevents loops |

## Liveness challenge (DISCOVER / ALIVE)

Cross-process discovery probes each candidate through its recorded Unix
socket using two protocol-v1 control kinds that ride the existing framed
transport (no second control plane):

- `DISCOVER` — the requester sends an envelope with `kind: discover`, the
  target peer as `recipient_peer_id`, and a single-use `secrets` nonce in
  `conversation_id`. The sender identity is the requester.
- `ALIVE` — the listener replies with `kind: alive`; `content` is canonical
  JSON carrying `{nonce, peer_id, instance_id, session_id, protocol,
  status}`. The requester compares the echoed nonce and every identity field
  exactly against the candidate record; any mismatch fails closed (the
  candidate is not listed).

PID is diagnostic only and never establishes liveness. Socket UID/inode are
captured from the actual bound listener at registration and used by the
repair fence.

## Receipts

Immediate transport-level receipts (never a claim that work completed):

- `queued` — host accepted delivery
- `held` — receiver policy holds the message
- `refused` — receiver policy rejects
- `unreachable` — target peer cannot be reached
- `expired` — envelope TTL elapsed before delivery
- `invalid` — malformed, wrong version, or validation failure
- `rate_limited` — sender exceeded the pair rate limit
- `over_capacity` — receiver pending inbox is full

## Limits and defaults

| Setting | Default |
|---|---|
| Content ceiling | 32 KiB |
| Frame ceiling | 64 KiB |
| Message TTL | 5 minutes |
| Connect timeout | 1 s |
| Receipt timeout | 3 s |
| Heartbeat interval | 15 s |
| Stale threshold | 45 s (+ handshake) |
| Max hop count | 4 |
| Rate limit | burst 5, sustained 20/min per pair |
| Inbox capacity | 100 pending per peer |
| Inbound policy | `accept` |

All limits are configurable within safe hard ceilings; invalid values fail
configuration validation.

## Forward compatibility

- Major version is part of `protocol` (`agent-peer/N`). Unknown major
  versions return an `invalid` receipt without crashing the receiver.
- Decoders reject unknown `kind` values; new kinds require a protocol bump.
- Unknown extra JSON fields are tolerated by decoding (forward-friendly) but
  never interpreted.
- JSON only — no executable object deserialisation, ever.

## Canonical form

Frames and persisted records use canonical JSON: sorted keys, compact
separators (`{"a":1,"b":2}`), UTF-8, RFC3339 UTC timestamps with `Z` and
microsecond precision. This keeps round-trips, tests and hashes stable.
