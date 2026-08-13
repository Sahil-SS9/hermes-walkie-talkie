# V1.1 Execution Ledger — Reconciled

This ledger records the release-relevant current state. Earlier phase detail
remains in Git history; it is not a substitute for evidence at the PR head.

## Current PR state

- Pull request: https://github.com/Sahil-SS9/hermes-walkie-talkie/pull/1
- Base: `main` at `f6d45194e3a906c13a2449805976d4e151430437`
- Reconciliation started from candidate `365ad07d09efb0c15021db1a68fe7b80298ca8d8`.
- The PR was clean and mergeable when this ledger was reconciled.

## GitHub CI evidence

GitHub Actions run `31723046182` passed all configured checks:

| Scope | Result |
|---|---|
| Python 3.11–3.13 on Ubuntu | passed |
| Python 3.11–3.13 on macOS | passed |
| Desktop build on Ubuntu, macOS and Windows | passed |
| Native Windows named-pipe and SID/DACL gate | passed |

The native job runs on `windows-latest` and exercises the real named-pipe,
ACL-owner-boundary and two-process exchange paths. It is native Windows
evidence, not a POSIX proxy.

## Reconciliation actions

- Corrected the Windows registry permission gate to use ACL ownership semantics
  rather than POSIX mode bits (`365ad07`).
- Corrected the E2E send seam so Alpha sends through Alpha's registered runtime
  instead of an unrelated controller (`ef8c355`).
- Reconciled the README, Windows docs and review packet to current native CI.
- Hardened the install/uninstall E2E assertion for environments where the
  plugin is also discovered as an installed entry point.
- Updated the deterministic verifier to accept a recorded native CI marker and
  removed its dependency on a retired local core worktree.

## Coverage still to run

- Windows wheel-install smoke.
- Full Hermes Desktop/Electron interaction on Windows.
- Live activation against a Hermes build containing the public host injection
  seam; upstream tracking is NousResearch/hermes-agent PR #85279.

## Release boundary

No tag, publication, installation or live activation is performed by this PR.
Those are separate, explicit operator actions after merge.
