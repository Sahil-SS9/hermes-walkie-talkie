# Operations runbook

## Health and diagnosis

```sh
hermes peer doctor            # full health snapshot + actionable remedies
hermes peer list              # live peers (alias, profile, surface, status)
```

`doctor` reports the seam state (the additive `inject_message` seam is
required for delivery), backend (`posix` on Linux/macOS, `windows` on
native Windows), and per-session presence.

## Common failures

| Symptom | Cause / fix |
|---|---|
| `seam_supported: false` | Host Hermes lacks the additive `inject_message` seam (mode/target_session). Upgrade the host; no private-field fallback exists (fail closed). |
| Peer not visible to another session | Both sessions must run under the same OS user and share the runtime root (`$XDG_RUNTIME_DIR/agent-peer/` or verified fallback). |
| Message stuck `held` | Recipient is mid-turn (busy) — queue-only delivery; the message releases on the next explicit drain. |
| `permission denied` on sockets | Owner-only roots: all dirs `0700`, files `0600`; symlinked or wrong-owner paths are refused. Remove foreign-owned entries. |
| Windows: wrong-user denied | Named-pipe DACL grants only the creator SID. Run sessions under the same Windows user. |

## Stale recovery

- `repair_stale()` runs at startup/doctor/owner-teardown: it re-reads and
  compares peer id, instance id, registry inode and socket inode
  immediately before any mutation; refuses when anything changed or
  liveness is ambiguous; never unlinks a path while a live listener remains
  bound (NG-07).
- Crash/restart: a crashed session's stale socket is reclaimed without
  deleting a replacement endpoint (tests in `test_runtime.py`,
  `test_stale_alerts.py`, `test_cross_platform_two_processes.py` on
  Windows).

## Desktop surface

```sh
hermes peer desktop install    # copy compiled bundle into HERMES_HOME/desktop-plugins/hermes-peer/
hermes peer desktop status
hermes peer desktop remove
```

Installing is explicit only — plugin load never writes to HERMES_HOME.
If the bundle is missing from the wheel (pre-build), install raises a
clear error instead of copying a stub.

## Limits (P10.8)

- Local same-user only: no remote execution, no cross-machine messaging.
- No nested groups: group membership is flat (agent_id set).
- Cancellation is advisory: a cancelled request never interrupts an
  active tool turn.
- Broadcasts are bounded (fan-out ceiling) and explicit about partial
  results; they never block the sender on a slow recipient.
- Windows release evidence is BLOCKED until a native Windows runner is
  approved.

## Upgrades and rollback

See `docs/upgrade-v1-to-v1-1.md`. Store migrations are incremental and
idempotent; a fresh install gets the latest schema directly. Rollback
means installing the previous wheel — schema v1..v4 are additive and old
rows remain readable as V1.
