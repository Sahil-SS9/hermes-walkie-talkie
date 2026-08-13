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
  - backends (`backends/`): backend-neutral local transport (ADR-0005).
    POSIX AF_UNIX is the reference backend; Windows named pipes with
    SID-bound DACLs are implemented and native-gated (release evidence
    requires a real Windows runner)
  - agent identity (`agent_identity.py`): stable per-profile UUID persisted
    owner-only under HERMES_HOME, never inferred from alias/path text
  - capabilities (`capabilities.py`): highest-mutual negotiation, fail-closed
  - protocol v2 (`protocol_v2.py`): typed V2 envelopes (message/receipt/
    discover/alive/request/request_status/request_cancel) with the
    incompatible/ambiguous receipt states
  - groups (`groups.py`): persistent groups CRUD — optimistic revision,
    ownership fence, unique normalised names, member caps
  - broadcast (`broadcast.py`): bounded broadcast engine — parent-first
    persist, deterministic child IDs, atomic created→in_flight
    single-writer gate, explicit partial results
  - workflows (`workflows.py`): pure request transition decision table
  - requests (`requests.py`): structured request/reply aggregate with
    idempotency keys, correlation, ordered event log
  - metrics (`metrics.py`): content-free counters/latency/failure-reason
  - events (`events.py`): bounded local event broker for the Desktop surface
  - health (`health.py`): actionable health snapshot with remedies

- **hermes_peer** — Hermes adapter. Public plugin API only (enforced by the
  HP-710 structural test). Owns:
  - config (`config.py`): `plugins.entries.hermes-peer.settings`
  - sessions (`sessions.py`): lifecycle hooks → peer registrations; host
    targets are opaque `surface:session_id` tokens captured from hook
    kwargs (never inherited thread context). `on_session_open` registers a
    peer while the host session is addressable (idle); `on_session_start` /
    `on_session_end` map turn activity to working/idle; reset rotates only
    the exact `old_session_id`
  - delivery (`delivery.py`): `<peer_message>` untrusted boundary marker,
    delivery via `ctx.inject_message(..., mode="queue", target_session=...)`,
    store-level dedup, fail-closed on unknown targets or missing seam
  - tools (`tools.py`): `peer_list_agents`, `peer_send_message`,
    `peer_read_inbox`, request tools (`peer_request_create/status/respond/
    cancel`) and group tools (`peer_group_list/peer_group_manage/
    peer_broadcast`)
  - commands (`commands.py`): `/peers`, `/peer-name`, `/peer-policy`,
    `/peer-inbox`, `/peer-groups`, `/peer-group`, `/peer-broadcast`,
    `/peer-request` and `hermes peer {list|send|inbox|name|policy|groups|
    group|broadcast|request|desktop|doctor}`
  - desktop install (`desktop_install.py`): explicit `hermes peer desktop
    install|status|remove` for the compiled Desktop bundle (never automatic)
  - dashboard (`dashboard/`): FastAPI plugin_api at
    `/api/plugins/hermes-peer` plus `manifest.json` for the Hermes Desktop
    plugin host (health/metrics/peers/groups/broadcast outcomes/inbox/
    requests and a /events WebSocket)
  - desktop (`desktop/`): React + TypeScript source built via vite into the
    compiled `plugin.js` + `style.css` shipped under
    `hermes_peer/assets/desktop`

## Discovery and identity

- **agent_peer.discovery.DiscoveryService** is the single read-only authority
  for listing and resolving peers (F-01). It reads a captured snapshot of
  every parseable registry record, validates filename/peer-ID agreement, safe
  socket containment, same-UID owner-only modes and the supported protocol,
  then probes each candidate through its recorded Unix socket with the
  DISCOVER/ALIVE challenge-response (`secrets` nonce, exact peer/instance/
  session/protocol comparison, bounded timeouts). Results are an immutable
  tuple stably sorted by `(name.casefold(), peer_id)`.
- Listing NEVER filters through the local connection map (`_peer_handles` is
  a runtime membership map, not a discovery source) and NEVER deletes,
  renames or rewrites registry/socket files.
- `resolve_peer(target)` is fail-closed: exact full `peer_id`; exact live
  `session_id`; `name~<short-peer-id>`; a bare name only when exactly one
  live peer has it; duplicate names return every candidate with full
  metadata (name, short/full peer ID, session, profile, surface, cwd/repo,
  status) — never a first-match pick.
- `repair_stale()` is the separate, explicit, race-safe cleanup path (startup
  repair / exact-owner teardown / doctor). It re-reads and compares peer ID,
  instance ID, registry inode and socket inode immediately before mutation,
  refuses when any value changed or liveness is ambiguous, and never unlinks
  a path while a live listener remains bound (NG-07).

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

## V1.1: agent identity, groups, broadcasts and requests

- **Agent identity (G2.3).** Every profile owns a stable UUID persisted
  owner-only under `HERMES_HOME/agent_identity.json` (`agent_identity.py`).
  Peer discovery and membership always address peers by `agent_id`; the
  per-session `peer_id` remains a session-scoped transport handle. A session
  reset keeps the same `agent_id` but rotates the `peer_id` (P9.6).
- **Protocol negotiation (G2.4).** Peers advertise `protocols`
  (`agent-peer/1`, `agent-peer/2`) and `capabilities`. Negotiation picks the
  highest mutual protocol; incompatible/ambiguous receivers return explicit
  receipt states and fail closed.
- **Groups (G3).** `GroupStore` keeps groups/group_members in SQLite
  (schema v3): owner fence, unique normalised names, optimistic revision,
  member caps (default 32, hard 128). Membership is by stable `agent_id`;
  aliases are display-only.
- **Broadcasts (G3).** `BroadcastEngine` persists the parent first, derives
  deterministic child IDs from `(broadcast_id, agent_id, peer_id)`, and uses
  an atomic `created→in_flight` transition so concurrent duplicate
  broadcasters converge on exactly one child per recipient. Fan-out is
  bounded; results are explicit per-recipient with queued/held/skipped/
  unreachable accounting; the sender is always self-excluded.
- **Structured requests (G4).** A pure decision table
  (`workflows.py`) drives `created → queued → accepted → in_progress →
  completed|failed|refused|cancelled|expired`; impossible/stale/out-of-order
  transitions are rejected, cancel is advisory, terminal states are frozen.
  `RequestStore` dedupes by `(sender, idempotency_key)` and keeps an ordered
  event log. Requests arrive at the recipient as the inert
  `<peer_request>` conversational marker — never as an executable command.
- **Surfaces.** A session may open on `cli`, `tui`/`dashboard` (collapsed to
  `tui`) or `desktop` (preserved distinctly). Delivery targets the opaque
  `host_target = surface:session_id` token.

## V1.1: Desktop surface and dashboard

- `hermes peer desktop install` copies the compiled bundle
  (`plugin.js` + `style.css`, vite build of `desktop/`) into
  `$HERMES_HOME/desktop-plugins/hermes-peer/` — **explicitly only**, never on
  plugin load (G6.9).
- The Hermes Desktop plugin host mounts the dashboard API at
  `/api/plugins/hermes-peer/` from `dashboard/plugin_api.py`: health,
  metrics, peers, groups + members, broadcast outcomes, inbox, requests +
  respond, and a `/events` WebSocket. The socket delegates auth to the
  dashboard's canonical `_ws_auth_ok` gate and always sends a frame
  (heartbeat) so clients never hang.
- The React panel (Peers/Groups/Inbox/Requests/Health tabs) keeps a
  profile-scoped cache so switching profiles never leaks another profile's
  state.

## Backend neutrality (ADR-0005)

- `agent_peer.backends` defines the transport/owner/path contract. POSIX
  AF_UNIX is the reference backend (same-UID check via SO_PEERCRED on
  Linux; fallback paths on macOS).
- Windows implements named pipes with SID-bound DACLs (owner-only,
  wrong-user denied at the OS boundary). All Windows tests are native-gated:
  they skip with an explicit reason on non-Windows and become real green
  evidence only on a native Windows runner (CI job `native-windows`).
- Native Windows CI now verifies the named-pipe and SID/DACL gates. Windows
  wheel-install and full Desktop/Electron interaction coverage remain
  explicitly unverified.

## Extension points

- New harness adapters implement discovery/identity/inject against the
  `agent_peer` core — the wire protocol and transport are harness-neutral.
- Future MCP exposure can wrap the three tools without touching the core.
