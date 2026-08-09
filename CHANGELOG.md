# Changelog

All notable changes to Hermes Walkie Talkie are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Initial v1 implementation of the Agent Peer core (`agent_peer`): peer
  identity, owner-local registry and presence, Unix-socket transport with a
  per-process selector supervisor, envelope v1 codec (`agent-peer/1`),
  persistent store, inbound policies (accept/hold/refuse), receipts,
  deduplication, rate/capacity limits and TTL handling.
- Initial Hermes adapter (`hermes_peer`): lifecycle hooks, config loader,
  tools (`peer_list_agents`, `peer_send_message`, `peer_read_inbox`),
  slash commands (`/peers`, `/peer-name`, `/peer-policy`, `/peer-inbox`),
  `hermes peer ...` CLI and bundled `peer-messaging` skill.
- Generic Hermes delivery seam (upstream candidate): additive
  `ctx.inject_message(..., mode=..., target_session=...)` with host-owned
  routing on CLI, TUI/dashboard and gateway surfaces.
- Documentation: architecture, protocol v1, security model, troubleshooting,
  ADRs, compatibility matrix and independent-review packet.

### Notes

- Linux is the release-blocking platform for v1. macOS CI is configured but
  its execution is deferred to post-goal approved remote CI. Windows is out
  of scope.
- This is an unreleased local review candidate (`v0.1.0-rc1`); no Git tag,
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

- Cross-machine transport, Windows named pipes, broadcasts/groups, file
  transfer and remote execution are out of scope for v1.
- macOS execution and the macOS peer-credentials path are configured but
  unverified until approved remote CI runs.
- A live model turn in the recipient session requires host credentials; the
  real-binary smoke test exercises delivery without a model call.
