# ADR-0005: Windows local transport and security backend

- Status: Accepted with NATIVE PROOF PENDING (11 August 2026)
- Plan: Hermes Walkie Talkie V1.1+ §3.2, §3.3, G5, P0.7, P2

## Context

V1 transport is AF_UNIX + `chmod`/`st_uid` on POSIX. V1.1 must run natively on
Windows 10/11 (G5.1): same-user enforcement via SID/DACL, owner-local roots
under `%LOCALAPPDATA%`, no XDG dependency (G5.5), no central daemon (G5.6).
`chmod`, `st_uid` and mocked `sys.platform` are not security evidence (G5.4,
G5.8).

## Phase 0 comparison (plan §3.3)

Candidate 1 — stdlib `multiprocessing.connection` with `AF_PIPE` plus an
authenticated owner-secret:
- Pro: zero new dependency.
- Con: the stdlib `AF_PIPE` listener does not expose fine-grained DACL control
  (`CreateNamedPipe` defaults apply); proving same-user isolation and bounded
  multiplexing requires native tests that were not runnable on the Linux
  implementation rig.

Candidate 2 — explicit Windows named-pipe ACL implementation using a narrowly
scoped Windows-only dependency (`pywin32`) with SID-bound DACL:
- Pro: explicit `CreateNamedPipe` security attributes, `GetCurrentProcess` /
  `ConvertStringSecurityDescriptorToSecurityDescriptor` with
  `(A;;GA;;;<user-SID>)` — provable same-user denial by construction.
- Con: one optional Windows-only dependency; Linux/macOS remain
  dependency-light (P2.7).

## Decision

**Select Candidate 2 — explicit SID-bound DACL via `pywin32`** for the native
Windows backend, conditional on the Phase 0 spike results recorded in
`docs/research/WINDOWS_TRANSPIKE.md`.

Reasoning: the ADR rule says *prefer stdlib only if all same-user, wrong-user,
stale-endpoint, spoofing, teardown and resource tests can be proven on native
Windows*. Those proofs require a native runner that is not available on this
implementation rig. Selecting the explicit-DACL dependency is the conservative
choice that does not silently downgrade security (no silent downgrade rule).

**Status: NATIVE PROOF PENDING.** The spike harness and native test matrix
(`tests/security/test_windows_owner_boundary.py`,
`tests/integration/test_windows_runtime.py`,
`tests/e2e/test_windows_native.py`) are written and will be executed on a
native Windows runner when one is approved. Until then, no Windows completion
claim is made (G5.8, NG-12, ACC-06/07).

## Backend-neutral contract (plan §3.2)

```python
class LocalTransportBackend(Protocol):
    kind: str
    def create_listener(self, *, instance_id: str, on_frame: Callable) -> ListenerHandle: ...
    def request(self, endpoint: TransportEndpoint, frame: bytes, *, timeout: float) -> bytes: ...
    def probe(self, endpoint: TransportEndpoint, challenge: bytes, *, timeout: float) -> bytes: ...
    def verify_remote_owner(self, connection: object) -> OwnerEvidence: ...
    def close(self) -> None: ...
```

Conformance tests run against both the existing POSIX backend and the Windows
backend. Backend stubs raise `NotImplementedError`; they never return fake
empty success.

## Consequences

- `agent_peer/backends/windows.py` implements real named-pipe code; Linux
  tests for it are supplementary only (P2 native gate).
- `pyproject.toml` gains an optional `[windows]` extra (`pywin32`) only if
  ADR-0005 final native proof confirms it; no core dependency change on
  Linux/macOS.
- Final status remains `PARTIAL` (IMPLEMENTED — WINDOWS RELEASE EVIDENCE
  verified by the native Windows CI job; no non-Windows run is substituted
  as Windows evidence.
