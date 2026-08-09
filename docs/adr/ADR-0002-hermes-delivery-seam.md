# ADR-0002 — Opaque Hermes target-session contract and delivery modes

- Status: Accepted (P0 architecture freeze, 9 August 2026)
- Related: plan §4.2, upstream issue #81885, PRs #64436, #70406, #80920

## Context

Peer messages must be delivered into the correct live Hermes conversation —
CLI, TUI/dashboard or gateway — without interrupting an active tool, and
without exposing Hermes routing internals to plugins. The existing public
seam `ctx.inject_message(content, role)` is CLI-only, uses private CLI
fields, interrupts busy sessions, and returns `False` outside the CLI.

## Decision

### Public seam (Hermes core, extended additively)

```python
ctx.inject_message(
    content,
    role="user",
    *,
    mode="queue",            # queue | steer | interrupt
    target_session=None,     # opaque exact-session target
) -> bool
```

- `queue` is the peer-messaging default. Idle target: start a new turn.
  Busy target: wait until a safe boundary; never terminate the active tool.
- `steer`: explicit mid-turn steering where the host supports it; `False`
  where it does not.
- `interrupt`: existing hard-interrupt behaviour, retained for compatibility.
- Unknown, closed, rotated or unauthorised targets fail closed (`False`).
- The existing two-argument call shape remains unchanged
  (backwards compatible).
- Gateway injection remains disabled per plugin unless
  `plugins.entries.<id>.allow_gateway_injection: true` is explicitly set.
- Injected text is conversational input only: it cannot invoke slash
  commands, approve tools or answer protected confirmation/clarification
  prompts.

### Host-owned routing (no plugin-private access)

- The CLI host exposes a public method (e.g. `cli.inject_message(...)`) that
  owns the pending/interrupt queues; `PluginContext.inject_message` delegates
  to it rather than touching `_interrupt_queue`/`_pending_input` itself.
- The TUI/dashboard host exposes `tui_gateway.server.inject_external_message`
  with exact-session targeting and busy-session FIFO queueing.
- The gateway host exposes an authorised route that reuses the stored
  platform route and queues behind active work; it revalidates authorisation
  at injection time.
- `target_session` is an opaque token chosen by the host. `hermes_peer`
  hides the exact parameter name behind `HostSessionTarget`.

### Compatibility

- `hermes_peer` feature-detects the seam. On hosts without it, the plugin
  reports a clear doctor/install error — never a private-field fallback.
- The Boolean return type is preserved; structured receipts belong to the
  Agent Peer transport contract (ADR-0003), not to Hermes core.

## Consequences

- Plugins can deliver safely to exact sessions on all three surfaces.
- The upstream PR approaches (#64436 gateway session injection, #80920
  dashboard routing) are reconciled into one additive host seam.
- The active tool is never interrupted unless the caller explicitly chooses
  `mode="interrupt"`.
- A plugin cannot escalate privilege: injected text is inert control-wise.
