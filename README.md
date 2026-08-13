# Hermes Walkie Talkie

![Walkie Talkie hero image](docs/assets/walkietalkie.jpeg)

V1.1 of the standalone `Sahil-SS9/hermes-walkie-talkie` plugin. It lets
independent Hermes sessions on the same machine, running as the same
operating-system user, find one another and exchange messages without a
parent/child relationship, a shared conversation, copy/paste, tmux, a
central orchestrator or a long-running daemon.

Walkie Talkie is a Hermes plugin first. It also ships a small,
Harness-neutral Python core (`agent_peer/`) that the plugin uses, and an
optional Hermes Desktop panel that surfaces the same state in the
Desktop UI.

## Features

- **Discovery.** Live peers on the local machine advertise themselves; a
  session can list them by surface (CLI, TUI, Desktop), profile and
  status.
- **Direct messages.** Address a peer by stable per-profile agent
  identity or by human-readable name. Delivery goes through the host's
  additive `inject_message` seam with `mode="queue"`.
- **Groups.** Persistent, owner-fenced groups with unique normalised
  names and bounded membership; flat, no nesting.
- **Broadcasts.** One sender, many recipients, deterministic child IDs,
  atomic single-writer gate and explicit per-recipient outcomes
  (`queued`, `held`, `skipped`, `unreachable`); sender self-excluded.
- **Request/reply.** Structured workflows with a transition decision
  table, idempotency keys, an ordered event log, recipient-only
  transitions and an inert `<peer_request>` conversational boundary;
  cancellation is advisory and never interrupts an active turn.
- **Local health.** A doctor snapshot with content-free metrics
  (counts, latency, failure reasons, held depth, stale-event fence) and
  actionable remedies.
- **Optional Desktop panel.** The Desktop plugin host installs a
  five-tab panel (Peers, Groups, Inbox, Requests, Health) backed by a
  profile-scoped read-only API. Installation is explicit; the plugin
  never writes to `HERMES_HOME` automatically.

## Boundaries

Walkie Talkie V1.1 deliberately does **not** do the following:

- **No cross-machine coordination.** Peers must be on the same host.
- **No remote command execution.** Inbound messages arrive at an inert
  conversational boundary; they carry no command authority.
- **No central daemon.** There is no long-running service. Each session
  is its own process; transport comes up and down with the session.
- **No interruption of busy sessions.** `mode="queue"` only; a busy
  recipient gets a `held` state and the message releases on the next
  explicit drain. Cancellation is advisory, not preemptive.
- **No wheel-install or Desktop interaction test on Windows.** The
  native named-pipe transport and SID-bound ACL gate are CI-verified on
  Windows; Windows wheel-install smoke and full Hermes
  Desktop/Electron interaction are follow-up coverage, not blockers.

## Quick start

Install the plugin from this checkout (or, once published, from the
default plugin index):

```bash
hermes plugins install /path/to/hermes-walkie-talkie
# or, once published:
# hermes plugins install Sahil-SS9/hermes-walkie-talkie
```

Enable it in the host's `config.yaml` (`plugins.enabled`) and restart
Hermes. Then, in two sessions on the same machine, run as the same OS
user:

```text
/peers                 # list live peer sessions
/peer-name backend     # give this session a human-readable name
/peer-policy accept    # accept incoming peer messages
```

In session A, ask the agent to message session B:

> Tell backend that `tenant_id` replaced `account_id` and ask whether
> the migration is complete.

The agent uses `peer_list_agents`, `peer_send_message` and
`peer_read_inbox` to discover, message and reply. No copy/paste.

**No-Hermes demo** (pure transport, no API keys):

```bash
uv run python scripts/demo_two_sessions.py
```

This spawns two disposable sessions named `architect` and `backend`,
exchanges a message, a reply and correlated receipts over real local
sockets, and exits.

## Commands and tools overview

Slash commands (Hermes TUI):

| Command | Purpose |
|---|---|
| `/peers` | List live peer sessions |
| `/peer-name <name>` | Set this session's human-readable name |
| `/peer-policy <mode>` | Set incoming-message policy |
| `/peer-inbox` | Read this session's inbox |
| `/peer-groups` | List groups visible to this session |
| `/peer-group <action>` | Create, join, leave or inspect a group |
| `/peer-broadcast <text>` | Send a broadcast |
| `/peer-request <action>` | Create, status, respond or cancel a request |

Agent tools (programmatic, exposed to the model):

| Tool | Purpose |
|---|---|
| `peer_list_agents` | Discover live peers |
| `peer_send_message` | Send a direct message |
| `peer_read_inbox` | Read received messages |
| `peer_request_create` | Start a structured request |
| `peer_request_status` | Inspect a request's state |
| `peer_request_respond` | Recipient transitions a request |
| `peer_request_cancel` | Sender cancels a request (advisory) |
| `peer_group_list` | List groups |
| `peer_group_manage` | Group membership operations |
| `peer_broadcast` | Send a broadcast |

CLI surface (no model in the loop):

```bash
hermes peer send <name> <message>
hermes peer desktop install
hermes peer desktop status
hermes peer desktop remove
```

Full documentation index:

- [Architecture](docs/architecture.md)
- [Protocol v1](docs/protocol.md)
- [Security model](docs/security.md)
- [Groups and broadcasts](docs/groups-and-broadcasts.md)
- [Structured request workflows](docs/request-workflows.md)
- [Hermes Desktop plugin](docs/desktop.md)
- [Operations runbook](docs/operations.md)
- [Upgrade V1 to V1.1](docs/upgrade-v1-to-v1-1.md)
- [Troubleshooting / doctor](docs/troubleshooting.md)
- [Compatibility](docs/compatibility.md)

## Windows support

V1.1 adds a native Windows local transport based on named pipes with
SID-bound DACLs. The transport and ACL gate have a native CI run on
GitHub Actions `windows-latest`; that pass is real Windows evidence,
not a Linux/macOS substitute.

What is **covered** by CI on Windows:

- Named-pipe transport unit behaviour (`tests/unit/test_windows_backend.py`)
- SID-bound ACL owner boundary: same-user success, wrong-user denial,
  spoofed-endpoint rejection, crash/stale fence
  (`tests/security/test_windows_owner_boundary.py`)
- Real two-process named-pipe exchange with crash/restart stale
  recovery (`tests/e2e/test_windows_native.py`,
  `tests/e2e/test_cross_platform_two_processes.py`)

What remains **follow-up coverage**, not inferred behaviour:

- A Windows wheel-install smoke test.
- Full Hermes Desktop/Electron interaction testing on Windows.

Walkie Talkie is therefore honest about Windows: the transport and
security gate are proven native; the desktop interaction and installer
smoke are not yet.

## Relationship to upstream Hermes

Walkie Talkie delivers inbound messages through the host's public
queued-injection seam: `ctx.inject_message(..., mode="queue",
target_session=...)`. That seam, with its `mode` (queue / steer /
interrupt) and `target_session` keyword arguments, lives in the
separate upstream change:

- [NousResearch/hermes-agent PR #85279](https://github.com/NousResearch/hermes-agent/pull/85279)

PR #85279 provides the **host-side queued / steering / interrupt
delivery controls**. Walkie Talkie V1.1 only uses the `mode="queue"`
half of that seam and never invokes steer or interrupt.

This README does not claim that V1.1 itself live-inspects every
subagent. V1.1 is the standalone plugin; live inspection of every
subagent is a host capability that depends on the upstream change
merging or an equivalent public API being available in the installed
host. When the host lacks the additive seam, Walkie Talkie's doctor
reports `seam_supported: false` and the plugin fails closed rather
than fall back to private host fields.

## Verification and CI

PR #1 has passed the GitHub Actions matrix on the current branch:

- Python 3.11-3.13 on Ubuntu and macOS
- Desktop build, typecheck, lint and tests on Ubuntu, macOS and Windows
- Native Windows named-pipe and ACL suites on `windows-latest`

Reproducible local verification:

```bash
uv run python scripts/verify_v1_1_plus_completion.py
uv build
uv run python scripts/verify_wheel_assets.py
```

Coverage gate (set in `scripts/coverage_gate.py`): 90% line / 85%
trust-delivery branch.

## Development

```bash
uv sync --group dev
uv run pytest -q
uv run ruff check .
uv run ty check agent_peer hermes_peer dashboard
uv run python scripts/coverage_gate.py
uv build
uv run python scripts/verify_wheel_assets.py

# Desktop surface (optional, Node 22):
cd desktop
npm ci
npm run typecheck && npm run lint && npm test && npm run build
```

Branch: `feat/hermes-walkie-talkie-v1-1`. Release notes live in
[CHANGELOG.md](CHANGELOG.md); the review packet is at
[docs/review/HANDOFF.md](docs/review/HANDOFF.md).

## Status

V1.1 is the current standalone release on `feat/hermes-walkie-talkie-v1-1`.
The Python core, the Hermes plugin, the local transports (POSIX AF_UNIX
and Windows named pipes with SID-bound DACLs), the Desktop bundle, the
CLI surface and the V1 to V1.1 upgrade path are all in this branch.

Open items, in priority order:

1. Windows wheel-install smoke (follow-up coverage).
2. Full Hermes Desktop/Electron interaction tests on Windows (follow-up
   coverage).
3. Live activation against a Hermes build that contains the upstream
   `inject_message` seam from PR #85279 (or equivalent public API) —
   until then, `mode="queue"` is the only mode Walkie Talkie will use.

## License

MIT — see [LICENSE](LICENSE).