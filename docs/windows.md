# Windows support

## Status

**IMPLEMENTED — NATIVE WINDOWS CI VERIFIED**

The Windows local transport uses named pipes with SID-bound DACLs. PR #1
ran the native-gated suites on GitHub Actions `windows-latest` and they
passed. This is real Windows evidence; a Linux/macOS pass is not substituted
for it.

The evidence covers the named-pipe transport, ACL owner boundary and
real two-process exchange. It does not claim a Windows wheel-install smoke
or a full Hermes Desktop/Electron interaction test; those remain separate
coverage work.

## Transport design (ADR-0005)

- Backend-neutral contract: `agent_peer/backends/base.py` defines
  `LocalTransportBackend` (bind/listen/connect/owner-verify), `PathBackend`
  and the owner-evidence types. Production selection goes through
  `get_transport_backend()` which reads the actual `sys.platform` (P1.5).
- Windows backend: `agent_peer/backends/windows.py`.
  - Named pipes under the logical path space, SID-bound DACL granting only
    the creating user's SID (owner-only; wrong-user denied at the OS
    boundary).
  - Path backend under `%LOCALAPPDATA%` with the same owner-only mode
    enforcement.
  - Optional extra `pywin32==310; sys_platform == 'win32'`.
- POSIX reference backend: `agent_peer/backends/posix.py` (AF_UNIX,
  same-UID via SO_PEERCRED on Linux, verified paths on macOS).

## Native-gated tests

These skip on non-Windows with an explicit reason and become real green
evidence only on a native Windows runner:

- `tests/unit/test_windows_backend.py` — named-pipe/DACL unit behaviour
- `tests/security/test_windows_owner_boundary.py` — same-user success,
  wrong-user denial, spoofed-endpoint rejection, crash/stale fence,
  teardown never touching a replacement
- `tests/e2e/test_windows_native.py` — backend selection, real two-process
  named-pipe exchange (P9.2), wrong-user DACL denial (P9.9)
- `tests/e2e/test_cross_platform_two_processes.py` — real two-process
  named-pipe exchange with crash/restart stale recovery (P9.7)

## CI

`.github/workflows/ci.yml` includes the `native-windows` job
(windows-latest) that runs the native-gated suites so the skips become
real evidence. Preparing the workflow is authorised by the plan; pushing a
branch or starting remote CI requires explicit approval.

## Paths

| Root | POSIX | Windows |
|------|-------|---------|
| Runtime (sockets/registry) | `$XDG_RUNTIME_DIR/agent-peer/` or secure fallback | `%LOCALAPPDATA%/agent-peer/` |
| State (SQLite) | `$XDG_STATE_HOME/agent-peer/` | `%LOCALAPPDATA%/agent-peer/state/` |

All roots/files are owner-only (`0700`/`0600` POSIX; SID-bound DACL on
Windows); symlinked or wrong-owner paths are refused.
