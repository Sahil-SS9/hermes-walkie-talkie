# Security review notes — V1.1+

## Scope

Peer messaging, groups, broadcasts, structured requests, desktop plugin
and the Windows named-pipe backend are new trust boundaries added in
V1.1. This file summarises the security posture and the tests that lock
it. It is producer evidence; the independent reviewer (P11.10–11.12)
attacks these boundaries explicitly.

## Boundaries and controls

1. **Same-user boundary.** All runtime/state paths are owner-scoped
   (`~/.local/state/agent-peer`, mode 0700); POSIX transport enforces
   same-UID via SO_PEERCRED and verifies the socket owner on every
   accept; no cross-user access is possible.
   Tests: `tests/security/test_permissions.py`, `test_symlink_races.py`,
   `test_windows_owner_boundary.py`, `test_posix_backend_errors.py`.

2. **Fail-closed transport.** Every malformed frame, oversized envelope,
   bad length prefix, unknown sender and foreign-owner connection is
   rejected with a typed error — never silently accepted. Send/recv
   resets surface as `UnreachableError` (regression locked by
   `test_transport_send_reset.py`).
   Tests: `tests/security/test_fuzzing.py`, `test_flood.py`,
   `test_concurrency.py`, `test_busy_target_queue_only.py`,
   `test_transport_contract.py`.

3. **Inert conversational input.** Peer messages and requests arrive as
   conversational text with explicit `<peer_request>` markers; they are
   NOT tools, commands or control-plane messages. No executable payloads,
   no object deserialisation (JSON only), no remote execution.
   Tests: `tests/security/test_control_injection.py`,
   `test_request_inert_control.py`.

4. **No content in observability.** Metrics/events/health carry counts,
   latencies and keys only — never message bodies, prompts, credentials
   or outbound telemetry.
   Tests: `tests/unit/test_metrics_no_content.py`, `test_stale_alerts.py`.

5. **Bounded resources.** Content ≤ 32 KiB, frame ≤ 64 KiB, rate limit
   burst 5/20 per pair, group cap 32 default / 128 hard, bounded fan-out
   concurrency, bounded event/metric ring buffers.
   Tests: `tests/security/test_flood.py`, `test_broadcast_limits.py`,
   `tests/unit/test_config_ceilings.py`.

6. **Desktop plugin boundary.** Wheel ships the bundle; installation is
   explicit-only (`hermes peer desktop install`); plugin load never
   auto-installs; dashboard WS auth delegates to the canonical
   `_ws_auth_ok` gate; polling remains the fallback.
   Tests: `tests/security/test_desktop_no_auto_install.py`,
   `tests/unit/test_desktop_install_edges.py`, `test_dashboard_api.py`.

7. **Windows named-pipe backend.** Fail-closed SID-bound DACL
   (`D:P(A;;GA;;;<sid>)`); connect-time credential checks; every method
   raises NotImplementedError unless pywin32 extras are present — an
   import failure can never open an insecure fallback. Native evidence
   is BLOCKED on this rig; the owner-boundary contract is asserted at
   the source level on Linux and natively on a Windows runner.
   Tests: `tests/security/test_windows_owner_boundary.py`,
   `tests/unit/test_windows_backend.py`, `tests/e2e/test_windows_native.py`.

8. **No cross-machine networking.** No TCP/UDP transport exists;
   `os.system`/shell interpolation banned by static audit.

## Static audits

- `tests/security/test_security_audit.py` — SEC-1010: no TODO/FIXME,
  no commented-out code, no shell interpolation, no `os.system`.
- `tests/unit/test_adapter_boundaries.py` — no placeholders, no broad
  import leaks across the core boundary.
- `tests/security/test_shutdown_and_gates.py` — no unbounded
  map/thread/FD growth; clean shutdown.

## Non-goals (V1.1)

No encryption in transit (same-user local sockets), no authentication
beyond the OS-user boundary, no cross-machine transport, no file
transfer, no remote execution.
