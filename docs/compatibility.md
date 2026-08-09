# Compatibility policy — Hermes seam feature detection (AP-006)

- Status: Accepted (P0 architecture freeze, 9 August 2026)

## Minimum host requirement

`hermes_peer` requires a Hermes build that exposes the public delivery seam:

```python
ctx.inject_message(content, role="user", *, mode="queue", target_session=None) -> bool
```

This means a Hermes core commit that includes the P1 delivery seam
(candidate branch `candidate/hermes-walkie-talkie-p1-20260809`, see the
Hermes core review packet for the exact commit) or any later commit with the
same signature.

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

## Tested matrix (v1 release candidate)

| OS | Python | Status |
|---|---|---|
| Linux | 3.11, 3.12, 3.13 | Verified locally (release-blocking) |
| macOS | 3.11–3.13 | CI configured; execution deferred to post-goal remote CI |
| Windows | — | Explicitly out of scope for v1 |

The minimum Hermes commit is recorded in `docs/review/VERIFICATION.md` and
`docs/review/HANDOFF.md` after the candidate freeze.
