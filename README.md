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
  addressing, protocol, transport, inbox, receipts, policy and persistence.
  Zero runtime dependencies, no Hermes imports.
- **Hermes Peer** (`hermes_peer`): a thin Hermes plugin — tools, slash
  commands, lifecycle hooks and safe delivery through the public
  `ctx.inject_message(..., mode="queue", target_session=...)` seam.
- **Protocol** `agent-peer/1`: versioned, bounded, JSON-over-`AF_UNIX`.

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

## Documentation

- [Architecture](docs/architecture.md)
- [Protocol v1](docs/protocol.md)
- [Security model](docs/security.md)
- [Troubleshooting / doctor](docs/troubleshooting.md)
- [Compatibility](docs/compatibility.md)
- [Review packet](docs/review/HANDOFF.md)

## Development

```bash
uv sync --group dev
uv run pytest -q
uv run ruff check .
uv run ty check agent_peer hermes_peer
uv build
```

Linux is the release-blocking platform for v1. macOS CI is configured;
macOS execution is verified post-goal on approved remote CI. Windows is out
of scope for v1.

## License

MIT — see [LICENSE](LICENSE).
