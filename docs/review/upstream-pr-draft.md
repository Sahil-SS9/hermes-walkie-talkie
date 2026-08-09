# Draft upstream PR description — Hermes generic plugin delivery seam (H-117)

Status: DRAFT — prepared locally for post-goal review. Not posted, not pushed.
Related: NousResearch/hermes-agent#81885 (local cross-session messaging),
open PRs #64436, #70406, #80920.

## Title

feat(plugins): additive inject_message seam — queue/steer/interrupt modes,
exact-session targets, inert-control guarantee

## Summary

Extends the public plugin seam `ctx.inject_message(content, role)` with two
keyword-only parameters and host-owned routing so plugins can deliver
conversational input to the correct live session — CLI, TUI/dashboard or
gateway — without interrupting active tools and without touching private
host fields.

```python
ctx.inject_message(content, role="user", *, mode="queue", target_session=None) -> bool
```

- `mode="queue"` (new default): idle target starts a new turn; a busy target
  queues at the safe boundary. The active tool is never interrupted.
- `mode="steer"`: explicit mid-turn steering where the host supports it.
- `mode="interrupt"`: existing hard-interrupt behaviour, unchanged.
- `target_session`: opaque exact-session token; unknown/closed/rotated/
  unauthorised targets fail closed.
- Injected text is conversational input only — it cannot invoke slash
  commands, approve tools or answer protected confirmation prompts.
- The two-argument call shape, Boolean return type and CLI-only fallback
  semantics for older callers are preserved.

## Host-owned routing (no plugin-private access)

- `HermesCLI.inject_message(...)` is the new public CLI host method; the
  plugin context delegates to it instead of poking `_pending_input` /
  `_interrupt_queue`.
- `tui_gateway.server.inject_external_message(...)` targets exact dashboard
  sessions (reconciles #80920's dashboard routing direction).
- `GatewayRunner.inject_plugin_message(...)` reuses the stored authorised
  route, queues behind active work, and is disabled per plugin unless
  `plugins.entries.<id>.allow_gateway_injection: true` (reconciles #64436's
  gateway injection gate).
- Internal injected events skip command dispatch and auth (conversational
  only) — inert-control guarantee.

## Compatibility with open upstream work

- #64436 (gateway plugin injection): same per-plugin gate and stored-route
  reuse; this seam keeps the sync `PluginContext` shape and delegates
  gateway work to the runner.
- #70406 (owner-local IPC into exact live gateway session): narrower,
  plugin-scoped equivalent; no new IPC surface here.
- #80920 (dashboard session injection): adopted its
  `inject_external_message` entry point with exact-session targeting.
- #81885 (local cross-session messaging): this seam is the host prerequisite;
  the harness-neutral peer transport ships separately in
  `hermes-walkie-talkie` (agent_peer + hermes_peer plugin).

## Commit series (local, review-ready)

1. `feat(plugins): additive inject_message seam — queue/steer/interrupt
   modes, exact targets, inert-control guarantee` (a346f63b82)
2. `docs(plugins): document inject_message modes, exact targets and surface
   guarantees` (9144932fcf)

## Testing

- 40 new RED-first tests across tests/hermes_cli, tests/test_tui_gateway_inject.py
  and tests/gateway/test_plugin_message_injection.py.
- Targeted and full Hermes regression results recorded in the goal ledger
  (P1 H-115/H-116) on the exact candidate commit.
