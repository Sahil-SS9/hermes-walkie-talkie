# Windows Transport Spike Report (P0.7)

- Date: 11 August 2026
- Plan: Hermes Walkie Talkie V1.1+ P0.7
- Spike location (disposable, quarantined): `/tmp/wtt-spike/windows_transport_spike.py`

## Purpose

Select and prove the native Windows local transport backend for the
backend-neutral contract (plan §3.2, §3.3, G5) before production code.

## What the spike does

1. Defines the exact `LocalTransportBackend` Protocol the production code must
   satisfy (`create_listener` / `request` / `probe` / `verify_remote_owner` /
   `close`), including `ListenerHandle`, `TransportEndpoint`, `OwnerEvidence`.
2. Provides a minimal POSIX reference implementation (AF_UNIX + chmod 700) that
   mirrors the accepted V1 implementation.
3. Runs the same behavioural test matrix that MUST later run against the
   Windows backend on native Windows:
   - same-user success
   - probe / alive proof
   - stale endpoint after close (must fail closed)
   - (native-only) wrong-user denial, spoofed endpoint, crash/stale record,
     teardown — via SID/DACL

## Result on Linux (this rig)

```text
Platform: linux
POSIX reference matrix: {'same_user_success': True, 'probe': True, 'stale_endpoint': True}
POSIX spike: PASS
NATIVE WINDOWS SPIKE: PENDING — no native Windows runner on this rig.
exit=3
```

- The harness itself is proven (exit 3 = pending-native marker, not a pass).
- The contract shape and the POSIX reference behaviour are directly exercised.

## ADR-0005 decision (recorded separately)

Candidate 2 — explicit Windows named-pipe ACL implementation with a narrowly
scoped Windows-only dependency (`pywin32`) + SID-bound DACL — is selected as
the conservative choice because the ADR rule only allows stdlib AF_PIPE if all
same-user/wrong-user/stale/spoof/teardown tests are proven on native Windows,
and no native runner is available on this implementation rig.

## Native gate (BLOCKED on this rig)

Per plan G5.8, NG-12, P2 native gate, ACC-06/07: the following MUST run on a
real Windows 10/11 runner before any Windows completion claim:

```bash
# On a native Windows runner, after production backend exists:
uv run pytest tests/security/test_windows_owner_boundary.py -q
uv run pytest tests/integration/test_windows_runtime.py -q
uv run pytest tests/e2e/test_windows_native.py -q
```

These test files are written in P2 and will execute there. The disposable
spike is quarantined at `/tmp/wtt-spike/` and is NOT production code.

## Conclusion

- Spike harness: PASS (Linux, POSIX reference).
- Native Windows proof: PENDING — no runner. Not claimed. (exit=3 marker)
- Final status impact: `PARTIAL` / `IMPLEMENTED — WINDOWS RELEASE EVIDENCE
  BLOCKED` until native proof lands.
