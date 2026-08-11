# Upgrading from V1 to V1.1

## Summary

V1.1 keeps the V1 envelope protocol (`agent-peer/1`) wire-compatible and
adds V2 typed envelopes, stable agent identity, groups, broadcasts,
structured requests, metrics/events/health, the Desktop plugin, and a
backend-neutral local transport (Windows named pipes).

## What does NOT change

- V1 tools (`peer_list_agents`, `peer_send_message`, `peer_read_inbox`)
  and slash commands (`/peers`, `/peer-name`, `/peer-policy`,
  `/peer-inbox`) behave identically.
- The local transport root layout and owner-only security model are
  unchanged on POSIX.
- Old V1 messages remain readable: schema migrations are additive; the
  V1 envelope shape is still accepted (protocol negotiation selects
  `agent-peer/1` against V1 peers).

## Store migrations

The SQLite store advances v1 → v2 → v3 → v4:

| Schema | Adds |
|---|---|
| v1 | V1 messages |
| v2 | protocol column (V2 negotiation) |
| v3 | groups, group_members, broadcasts, broadcast_children |
| v4 | requests, request_events |

- Migrations are incremental and idempotent (`store.py`).
- A fresh install creates the latest schema directly (no migration run).
- An existing DB upgrades in place; old rows stay readable as V1.

## What an operator must do

1. Install the V1.1 wheel (`uv pip install` / your package manager).
2. Run `hermes peer doctor` — verify `seam_supported: true` (the additive
   inject_message seam is required for V1.1 delivery).
3. Optional: `hermes peer desktop install` for the Hermes Desktop surface
   (explicit, never automatic).
4. Verify peers: `hermes peer list` should show the same live peers.

## Rollback

Install the previous V1 wheel. Because schemas are additive, V1 reads the
same store without migration; V1.1 rows (groups/requests) are simply not
exercised. No destructive migration exists.

## Known limits after upgrade

- Cancellation is advisory (no interrupt seam).
- Groups are flat — no nesting.
- Broadcasts are bounded and report partial results explicitly.
- Windows release evidence is BLOCKED until a native Windows runner is
  approved (see `docs/windows.md`).
