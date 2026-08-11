# Windows native release evidence

## Status

**BLOCKED — no native Windows runner approved on this rig.**

Per the plan's remote-CI approval gate and ADR-0005, Windows native
release evidence can never be marked COMPLETE on this Linux rig. The
deterministic verifier (`scripts/verify_v1_1_plus_completion.py`)
rejects any attempt to do so: on non-win32 platforms the
`windows-native-evidence` check is hard-coded to FAIL/BLOCKED.

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

## What evidence is missing (why BLOCKED)

- A real `windows-latest` GitHub Actions run of the full matrix.
- Native named-pipe connect/deny/teardown observed on Windows.
- Windows-home wheel install (`P10.5` Windows leg).
- Desktop-Electron-on-Windows E2E (`P9.4`).

## How to unblock

1. Sahil approves remote CI (plan approval gate: workflows are prepared
   in `.github/workflows/` but not pushed).
2. Push a branch and let `windows-latest` run the suite.
3. Re-run the deterministic verifier on a Windows runner: the
   `windows-native-evidence` check flips to COMPLETE only when the
   `NATIVE PROOF COMPLETE` marker is present in this file AND the
   platform is win32.

## Marker

To mark native proof complete (Windows runner only, after evidence):

```
NATIVE PROOF COMPLETE
```

Nothing in this repository may write that marker from Linux.
