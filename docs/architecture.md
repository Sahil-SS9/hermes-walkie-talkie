# Architecture

Hermes Walkie Talkie — same-machine, cross-session agent messaging. Locked
by ADR-0001 (repository/process/runtime), ADR-0002 (Hermes delivery seam)
and ADR-0003 (envelope protocol).

## Components

```
┌─────────────────────────────┐        ┌─────────────────────────────┐
│ Hermes session A (CLI/TUI)  │        │ Hermes session B (CLI/TUI)  │
│  hermes_peer (adapter)      │        │  hermes_peer (adapter)      │
│   │ hooks / tools / cmds    │        │   │ hooks / tools / cmds    │
│   ▼                         │        │   ▼                         │
│ PeerSessionManager          │        │ PeerSessionManager          │
│   ▼                         │        │   ▼                         │
│ PeerRuntimeManager  ────────┼────────┼──► PeerRuntimeManager        │
│ (one selector thread)       │  AF_UNIX│ (one selector thread)       │
│   ▲                         │        │   ▲                         │
│ Registry (owner-local JSON) │◄───────┼── shared runtime root        │
│ Store (owner-local SQLite)  │◄───────┼── shared state root          │
└─────────────────────────────┘        └─────────────────────────────┘
```

Two packages:

- **agent_peer** — harness-neutral core. Zero runtime dependencies, no
  Hermes imports (enforced by a structural test). Owns:
  - identity (`identity.py`): UUID peer/instance ids, host metadata, aliases
  - protocol (`models.py`, `codec.py`): immutable envelope models, canonical
    JSON, length-prefixed framing with pre-buffer oversize rejection
  - paths (`paths.py`): owner-only runtime roots, short socket paths with
    relocation under deep trees, symlink/wrong-owner refusal
  - registry (`registry.py`): atomic per-peer JSON records, presence,
    stale pruning only after expiry + failed handshake
  - transport (`transport.py`, `runtime.py`): `PeerClient` (bounded
    connect/receipt timeouts) and `PeerRuntimeManager` — one daemon selector
    thread per process serving every session socket; same-UID checks;
    non-blocking I/O so a stalled client cannot block other peers
  - persistence (`store.py`): SQLite WAL, idempotent migrations, dedup
    (one row per message_id), bounded retention
  - policy (`policy.py`): accept/hold/refuse, sliding-window rate limits,
    capacity caps, TTL and hop-count rejection with explicit receipts

- **hermes_peer** — Hermes adapter. Public plugin API only (enforced by the
  HP-710 structural test). Owns:
  - config (`config.py`): `plugins.entries.hermes-peer.settings`
  - sessions (`sessions.py`): lifecycle hooks → peer registrations; host
    targets are opaque `surface:session_id` tokens captured from hook
    kwargs (never inherited thread context)
  - delivery (`delivery.py`): `<peer_message>` untrusted boundary marker,
    delivery via `ctx.inject_message(..., mode="queue", target_session=...)`,
    store-level dedup, fail-closed on unknown targets or missing seam
  - tools (`tools.py`): `peer_list_agents`, `peer_send_message`,
    `peer_read_inbox`
  - commands (`commands.py`): `/peers`, `/peer-name`, `/peer-policy`,
    `/peer-inbox` and `hermes peer {list|send|inbox|name|policy|doctor}`

## Process model

- One `PeerRuntimeManager` per process; first peer registration starts the
  supervisor thread, the last teardown stops it. No daemon, no thread per
  session, no per-message threads.
- A CLI process normally owns one peer; a TUI/gateway process may own
  several peers through the same supervisor.

## Delivery semantics

- Idle target → the host starts a new turn (inject `mode="queue"`).
- Busy target → queued at the safe boundary; the active tool is never
  interrupted (`mode="queue"` never touches the interrupt queue).
- Receipts are transport-level only: `queued` means accepted for delivery,
  never that the recipient completed work.

## Shared owner-local roots

- Runtime (sockets + registry): `$XDG_RUNTIME_DIR/agent-peer/` when secure,
  else a verified short fallback under `$XDG_STATE_HOME`; sockets relocate
  to `/tmp/agent-peer-<uid>` when the root exceeds the AF_UNIX bound.
- State (SQLite): `${XDG_STATE_HOME:-~/.local/state}/agent-peer/`.
- All dirs `0700`; all files `0600`; symlinked or wrong-owner paths refused.
- Shared roots are what make cross-profile and cross-worktree discovery
  work: every session under the same OS user sees the same peers.

## Hermes delivery seam (upstream candidate)

`ctx.inject_message(content, role="user", *, mode="queue", target_session=None)`
with host-owned routing on CLI (`HermesCLI.inject_message`), dashboard
(`tui_gateway.server.inject_external_message`) and gateway
(`GatewayRunner.inject_plugin_message`, gated per plugin via
`allow_gateway_injection`). See ADR-0002 and `docs/review/upstream-pr-draft.md`.

## Extension points

- New harness adapters implement discovery/identity/inject against the
  `agent_peer` core — the wire protocol and transport are harness-neutral.
- Future MCP exposure can wrap the three tools without touching the core.
