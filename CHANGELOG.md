# Changelog

All notable changes to Hermes Walkie Talkie are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- V1.1: stable per-profile agent identity (owner-only UUID under
  HERMES_HOME, never inferred from alias/path text).
- V1.1: protocol negotiation (`agent-peer/1` unchanged; `agent-peer/2`
  typed envelopes) and capability negotiation (highest-mutual, fail-closed).
- V1.1: persistent groups (owner fence, unique normalised names, member
  caps 32/128) and bounded broadcasts (deterministic child IDs, atomic
  single-writer gate, explicit queued/held/skipped/unreachable results,
  sender self-exclusion).
- V1.1: structured request/reply workflows (pure transition decision
  table, idempotency keys, ordered event log, recipient-only transitions,
  inert `<peer_request>` conversational boundary, advisory cancel).
- V1.1: content-free metrics, bounded event broker, actionable health
  snapshot, stale alerts with exact-instance fence.
- V1.1: backend-neutral local transport — POSIX AF_UNIX reference plus
  Windows named pipes with SID-bound DACLs (native-gated).
- V1.1: Hermes Desktop plugin — dashboard FastAPI backend
  (`/api/plugins/hermes-peer`, /events WebSocket with heartbeat), React
  panel (Peers/Groups/Inbox/Requests/Health) with profile-scoped cache,
  explicit `hermes peer desktop install|status|remove` (never automatic).
- V1.1: group/broadcast/request tools and slash/CLI commands; expanded
  doctor.
- V1.1: real-process E2E harness (two real Hermes binaries with fake-model
  deferred tool dispatch): discovery, structured requests, broadcasts and
  desktop surface.
- Docs: architecture, security, groups-and-broadcasts, request-workflows,
  desktop, windows, operations runbook, upgrade guide, compatibility.

### Notes

- Native Windows CI is verified on GitHub Actions `windows-latest` for the
  named-pipe, SID/DACL and real two-process exchange gates (run 31723046182).
  A Windows wheel-install smoke and full Desktop/Electron interaction remain
  separate follow-up coverage.
- This is an unreleased release candidate (`v0.1.0-rc1`); no Git tag,
  package publication or live activation has occurred.

## [0.1.0-rc1] — unreleased local review candidate

### Verified capabilities (Linux, exact candidate)

- Discovery of same-user sessions across profiles and worktrees via a shared
  owner-local runtime root (0700 dirs, 0600 files, symlink/wrong-owner
  refusal, AF_UNIX path relocation for deep roots).
- Point-to-point messaging and replies over per-session Unix sockets served
  by one selector thread per process; same-UID checks; stalled-client
  isolation; bounded connect/receipt timeouts.
- Envelope protocol `agent-peer/1` (canonical JSON, length-prefixed framing
  with pre-buffer oversize rejection, TTL, hop cap, dedup).
- Inbound policies accept/hold/refuse with explicit receipts
  (queued/held/refused/unreachable/expired/invalid/rate_limited/
  over_capacity); rate and capacity limits; persistent SQLite store with
  WAL, idempotent migrations and bounded retention.
- Hermes adapter: lifecycle hooks, three tools, four slash commands,
  `hermes peer {list|send|inbox|name|policy|doctor}`, bundled skill,
  `<peer_message>` untrusted boundary, queue-mode exact-session delivery via
  the public inject seam (CLI/TUI/gateway), inert-control guarantee.
- Security: payload fuzzing, flood/capacity bounds, concurrency stress,
  storage-failure observability, no-TCP proof, log-redaction audit, static
  audits, coverage gate (90% line / 85% trust-delivery branch).

### Limitations

- Cross-machine transport, file transfer and remote execution are out of
  scope for V1.1.
- Groups are flat (no nesting); cancellation is advisory (no interrupt
  seam).
- Windows native release evidence is BLOCKED until an approved native
  Windows runner exists.
- macOS execution and the macOS peer-credentials path are configured but
  unverified until approved remote CI runs.
- A live model turn in the recipient session requires host credentials; the
  real-binary E2E exercises delivery through the deterministic fake model
  server (no fabricated model credentials).
