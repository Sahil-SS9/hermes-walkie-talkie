# Hermes Walkie Talkie

Same-machine, cross-session agent messaging for AI harnesses — Hermes first.

Independent agent sessions on one machine can discover one another and
exchange messages without a parent/child relationship, a shared
conversation, manual copy/paste, tmux, a central orchestrator or a daemon.

```
Terminal / Process A                     Terminal / Process B
┌─────────────────────────┐             ┌─────────────────────────┐
│ Hermes Session          │             │ Hermes Session          │
│ name: architect         │             │ name: backend           │
└────────────┬────────────┘             └────────────┬────────────┘
             │  peer_send_message()                  │
             └──────────────►  local peer transport  ─┘
                             │  (Unix-domain socket)  │
             ◄───────────────┘          reply        │
```

## What it is

- **Agent Peer** (`agent_peer`): a harness-neutral Python core — discovery,
  addressing, protocol, transport, inbox, receipts, policy, persistence,
  stable agent identity, groups, broadcasts, structured request/reply
  workflows, metrics/events/health and backend-neutral local transport
  (POSIX AF_UNIX reference; Windows named pipes with SID-bound DACLs).
  Zero runtime dependencies, no Hermes imports.
- **Hermes Peer** (`hermes_peer`): a thin Hermes plugin — tools, slash
  commands, lifecycle hooks, safe delivery through the public
  `ctx.inject_message(..., mode="queue", target_session=...)` seam, and
  explicit desktop install for the Hermes Desktop plugin host.
- **Protocols** `agent-peer/1` (V1, unchanged) and `agent-peer/2`
  (V1.1 typed envelopes): versioned, bounded, JSON-over-`AF_UNIX`.

## Quick start

```bash
# Install the plugin (from this repository checkout)
hermes plugins install /path/to/hermes-walkie-talkie
# or via GitHub once published:
# hermes plugins install Sahil-SS9/hermes-walkie-talkie

# Enable it in config.yaml (plugins.enabled) and restart Hermes.
# Open two Hermes sessions, then:

/peers                 # list live peer sessions
/peer-name backend     # give this session a human-readable name
/peer-policy accept    # accept incoming peer messages

# In session A, ask the agent to message session B:
#   "Tell backend that tenant_id replaced account_id and ask whether the migration is complete."
```

The agent uses `peer_list_agents`, `peer_send_message` and
`peer_read_inbox` to discover, message and reply — no copy/paste.

**No-Hermes demo** (pure transport, no API keys):

```bash
uv run python scripts/demo_two_sessions.py
```

Spawns two disposable sessions named `architect` and `backend`, exchanges a
message, a reply and correlated receipts over real Unix sockets.

## Documentation

- [Architecture](docs/architecture.md)
- [Protocol v1](docs/protocol.md)
- [Security model](docs/security.md)
- [Groups and broadcasts](docs/groups-and-broadcasts.md)
- [Structured request workflows](docs/request-workflows.md)
- [Hermes Desktop plugin](docs/desktop.md)
- [Windows support](docs/windows.md)
- [Operations runbook](docs/operations.md)
- [Upgrade V1 → V1.1](docs/upgrade-v1-to-v1-1.md)
- [Troubleshooting / doctor](docs/troubleshooting.md)
- [Compatibility](docs/compatibility.md)
- [Review packet](docs/review/HANDOFF.md)

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
cd desktop && npm ci && npm run typecheck && npm run lint && npm test && npm run build
```

Linux is the release-blocking platform for V1.1. macOS CI is configured;
macOS execution is verified post-goal on approved remote CI. Windows is
implemented but native release evidence is BLOCKED until an approved
native Windows runner exists (see [docs/windows.md](docs/windows.md)).

## License

MIT — see [LICENSE](LICENSE).
