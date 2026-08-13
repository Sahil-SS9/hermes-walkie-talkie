# Verification Record — PR #1 reconciliation

This record supersedes historical freeze notes in this directory where they
conflict with the current pull request.

## Current candidate

- Repository: `Sahil-SS9/hermes-walkie-talkie`
- Pull request: https://github.com/Sahil-SS9/hermes-walkie-talkie/pull/1
- Base: `main` at `f6d45194e3a906c13a2449805976d4e151430437`
- Candidate at reconciliation start: `365ad07d09efb0c15021db1a68fe7b80298ca8d8`
- Merge state: clean and mergeable at reconciliation start.

A reconciliation commit after this record changes the candidate SHA. Reviewers
must take the actual PR head from GitHub, not a historic SHA copied here.

## Direct GitHub evidence

GitHub Actions run `31723046182` passed every configured PR check:

| Area | Evidence |
|---|---|
| Python | 3.11–3.13 passed on Ubuntu and macOS |
| Desktop | build, typecheck, lint and tests passed on Ubuntu, macOS and Windows |
| Native Windows | named-pipe / SID-DACL / multi-process gate passed on `windows-latest` |

The native Windows run is evidence for the Windows transport and ACL gates. It
does not claim a Windows wheel-install smoke or full Desktop/Electron
interaction coverage.

## Local verification required at the final PR SHA

Run from a clean checkout:

```bash
uv run pytest -q
uv run ruff check .
uv run ty check agent_peer hermes_peer dashboard
uv run python scripts/coverage_gate.py
uv build
uv run python scripts/verify_wheel_assets.py
uv run python scripts/verify_v1_1_plus_completion.py
```

The deterministic verifier checks its own worktree before and after its test
and coverage gates, package assets and the committed native-Windows CI marker.

## Hermes host dependency

Walkie Talkie delivers inbound messages through Hermes' public queued injection
seam. The separate upstream dependency is PR #85279:

https://github.com/NousResearch/hermes-agent/pull/85279

That PR is open and green at the time of reconciliation. Walkie Talkie can be
merged as a standalone plugin release candidate, but live activation requiring
queue/steer/interrupt host behaviour remains conditional on #85279 merging or
the equivalent public Hermes API being available in the installed host.

## Remaining coverage, not hidden blockers

- Windows wheel-install smoke.
- Full Hermes Desktop/Electron interaction on Windows.
- Live activation against a Hermes build containing the upstream host seam.

## Release boundary

No tag, package publication or live activation is implied by a merge. Merge is
the code and evidence decision; release/activation remains an explicit later
operator action.
