# Windows native release evidence

## Status

**NATIVE WINDOWS CI VERIFIED — 2026-08-13**

PR #1 ran the native Windows suite on GitHub Actions `windows-latest`.
The named-pipe transport, SID/DACL owner boundary, and real two-process
exchange all passed in run `31723046182` (job `94525162946`). This is native
Windows evidence; no Linux or macOS result is being used as a substitute.

The deterministic verifier accepts this committed evidence marker. It still
runs the local suite and coverage gate, and it does not claim a Windows
wheel-install smoke or a full Hermes Desktop/Electron interaction test.

## What is implemented (code, not evidence)

- `agent_peer/backends/windows.py` — fail-closed named-pipe backend:
  - SID-bound DACL on the pipe (`D:P(A;;GA;;;<sid>)`) so only the
    creating user's SID can connect,
  - `SECURITY_IMPERSONATION`-style connect-time credential checks
    (fail-closed on unknown/foreign SID),
  - bounded connect/receive timeouts, framed protocol over the pipe,
  - listener authority carrying the owner SID,
  - `_native()` guard: every production method raises
    `NotImplementedError` unless the pywin32 extras are installed,
    so an import failure can never open an insecure fallback.
- `agent_peer/platform_paths.py` — Windows state/runtime path selection.
- `tests/unit/test_windows_backend.py` — 18 native-gated tests that
  SKIP on non-Windows with an explicit native-required reason (they are
  NOT counted as evidence on Linux).
- `tests/security/test_windows_owner_boundary.py` — owner-boundary
  assertions over the SDDL/ACL contract (source-level on Linux).
- `tests/e2e/test_windows_native.py` — consolidated native E2E gate
  (backend selection, SID/DACL ownership, wrong-user denial) that runs
  ONLY on a Windows runner; on Linux it skips with `native-required`.

## What evidence remains out of scope

- Windows-home wheel install (`P10.5` Windows leg).
- Desktop-Electron-on-Windows interaction E2E (`P9.4`).

These are not claimed by the native transport/ACL CI run.

## Follow-up coverage

1. Run the Windows wheel-install smoke from the CI matrix.
2. Run a full Hermes Desktop/Electron interaction test on Windows.
3. Record each result here with its run URL and exact scope.

## Evidence marker

```
NATIVE PROOF COMPLETE — GitHub Actions run 31723046182
```

This marker records the completed native transport/ACL proof. It must not be
used to claim the two follow-up coverage items above.
