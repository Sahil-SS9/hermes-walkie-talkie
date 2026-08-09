# ADR-0001 — Repository boundaries, process model and runtime roots

- Status: Accepted (P0 architecture freeze, 9 August 2026)
- Related: source brief (cross-session messaging), plan §1, §3

## Context

Hermes Walkie Talkie must let independent agent sessions on one machine
discover and message each other without a central daemon, shared
conversation or manual copy/paste. Two code surfaces exist: a harness-neutral
peer core and a Hermes-specific adapter. The system must be secure
(same-owner only), lightweight (no daemon, no thread per session) and
recoverable (crash-safe registration).

## Decision

### Repository boundaries

- The standalone public repository `hermes-walkie-talkie` owns everything:
  the harness-neutral `agent_peer` package, the Hermes adapter `hermes_peer`,
  plugin entry points, skill, docs, tests and CI.
- The Hermes core candidate lives in an isolated worktree
  (`hermes-walkie-talkie-core`) on top of the canonical Hermes checkout. The
  only Hermes core change permitted is the generic public delivery seam
  (see ADR-0002). No peer-specific code ever lands in Hermes core.
- The harness-neutral core (`agent_peer`) must not import Hermes modules;
  a structural test enforces this.

### Process model

- `PeerRuntimeManager` is process-global. It owns exactly one daemon thread
  running a `selectors.DefaultSelector` loop.
- Each live conversation registers its own Unix-domain socket with that
  supervisor. A CLI process normally owns one peer; a TUI/gateway process may
  own several peers without creating one thread per session.
- No permanent broker or daemon: when the last peer in a process
  unregisters, the supervisor thread stops.
- Hermes lifecycle hooks register, update and remove peers. Socket cleanup is
  additionally protected by `atexit` and stale-registry recovery.

### Runtime and persistent paths (shared owner-local roots)

- Runtime registry and sockets on Linux: `$XDG_RUNTIME_DIR/agent-peer/` when
  secure and available; otherwise a verified short `0700` owner-local
  fallback (never under a profile-specific `HERMES_HOME`).
- Persistent state: `${XDG_STATE_HOME:-~/.local/state}/agent-peer/messages.sqlite3`.
- Runtime directories are `0700`; registry files, sockets and the SQLite
  database are owner-only (`0600` or stricter). Symlinked or wrong-owner
  runtime paths are refused.
- Shared owner-local paths are required so different Hermes profiles,
  terminals and Git worktrees can discover one another.

## Consequences

- One supervisor thread per process keeps idle cost near zero.
- Sockets are short-lived, per-session files that are easy to clean up and
  audit.
- Cross-profile discovery works without touching any profile's private state.
- The no-daemon rule means each process is fully independent; there is no
  single point of failure beyond the filesystem.
