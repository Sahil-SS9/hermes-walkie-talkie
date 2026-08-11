# Compatibility policy — Hermes seam feature detection (AP-006)

- Status: Accepted (P0 architecture freeze, 9 August 2026)

## Minimum host requirement

`hermes_peer` requires a Hermes build that exposes the public delivery seam:

```python
ctx.inject_message(content, role="user", *, mode="queue", target_session=None) -> bool
```

plus the generic lifecycle and command-context seams added by the remediation
candidate:

```python
# on_session_open lifecycle hook (fires when a live session is addressable,
# BEFORE its first model turn — distinct from on_session_start)
ctx.register_hook("on_session_open", handler)

# exact-session command context (opt-in; legacy one-argument handlers
# remain unchanged)
def handler(raw_args, *, session_id=None, platform=None, session_target=None): ...
```

This means a Hermes core commit that includes the P1 delivery seam and the
remediation lifecycle/context seams (candidate branch
`candidate/hwt-core-remediation-20260809`, see the remediation review packet
for the exact commit) or any later commit with the same signatures.

## Feature detection

1. At plugin load, `hermes_peer` inspects the live `PluginContext`:
   - `inject_message` exists and accepts `mode`/`target_session` keyword
     arguments (checked via `inspect.signature`), and
   - the host exposes a public routing entry for the current surface.
2. If the seam is missing or incomplete, the plugin:
   - fails to load with a clear doctor/install error naming the missing
     capability and the minimum required Hermes commit;
   - never falls back to private fields (`_cli_ref`, `_pending_input`,
     `_interrupt_queue`, gateway internals) — private-field fallback is
     banned outright.

## Hard rules

- No import or attribute access of any name starting with `_` on Hermes
  host objects (`PluginContext` internals, CLI internals, gateway internals).
  Enforced by the HP-710 structural test.
- `hermes_peer` may import only public modules: `hermes_cli.plugins`
  (types), `hermes_cli.profiles`, `hermes_cli.config`, and the host seam
  entry points documented in ADR-0002.
- If the host API is unavailable, fail clearly. Never silently degrade.

## Tested matrix (V1.1 release candidate)

| OS | Python | Status |
|---|---|---|
| Linux | 3.11, 3.12, 3.13 | Verified locally (release-blocking) |
| macOS | 3.11–3.13 | CI configured; execution deferred to post-goal remote CI |
| Windows | 3.12 | Backend implemented; native release evidence BLOCKED (no approved native runner). Final status `IMPLEMENTED — WINDOWS RELEASE EVIDENCE BLOCKED` |

Windows V1.1 support is NOT a v1.1 blocker claim: the named-pipe/DACL
transport is implemented and native-gated, but the gated tests only become
green evidence on a real Windows runner (CI job `native-windows`).

The minimum Hermes commit is recorded in `docs/review/VERIFICATION.md` and
`docs/review/HANDOFF.md` after the candidate freeze.

## Hermes core requirement (candidate seam)

| Hermes source | Commit | Notes |
|---|---|---|
| Isolated candidate worktree | `candidate/hermes-walkie-talkie-p1-20260809` (see review packet for the exact SHA) | Contains the additive `inject_message` seam (P1) |
| Any later Hermes build | — | Same signature `(content, role="user", *, mode, target_session)` |

Without the seam the plugin loads but delivery is disabled with a clear
warning (`hermes peer doctor` reports it). macOS runtime verification of the
peer-credentials fallback is configured in CI but unexecuted until approved
remote runs exist.
