# Hermes Walkie Talkie V1.1 — Release Review Handoff

Status: PR #1 is an open release candidate. It has not been tagged, published
or activated in a live Hermes profile.

## Current candidate

- Repository: `Sahil-SS9/hermes-walkie-talkie`
- Base branch: `main`
- Candidate branch: `feat/hermes-walkie-talkie-v1-1`
- Pull request: https://github.com/Sahil-SS9/hermes-walkie-talkie/pull/1
- Merge state: clean and mergeable at the time this packet was reconciled.

Use the PR head SHA shown by GitHub when reviewing. Do not rely on historic
freeze SHAs in earlier review records: they pre-date the Windows remediation
commits.

## What V1.1 adds

- Stable per-profile `agent_id`, protocol/capability negotiation and
  deterministic agent-to-peer routing.
- Persistent flat groups, bounded broadcasts and explicit per-recipient
  outcomes.
- Structured request/reply workflows with idempotency, ordered state events
  and advisory cancellation.
- Local health snapshots, content-free metrics and bounded local events.
- Hermes tools, slash commands and an explicit-install Desktop collaboration
  panel.
- Backend-neutral local transport: POSIX AF_UNIX and Windows named pipes with
  SID-bound DACLs.

## Evidence

GitHub Actions run `31723046182` passed every defined PR check:

- Python 3.11–3.13 on Ubuntu and macOS.
- Desktop typecheck, lint, tests and build on Ubuntu, macOS and Windows.
- Native Windows named-pipe and SID/DACL suites on `windows-latest`.

The native Windows job covers the transport, owner-boundary and real
multi-process exchange gates. It does not claim a Windows wheel-install smoke
or a full Hermes Desktop/Electron interaction test.

## Local verification

Run from this repository with a clean worktree:

```bash
uv run pytest -q
uv run ruff check .
uv run ty check agent_peer hermes_peer dashboard
uv run python scripts/coverage_gate.py
uv build
uv run python scripts/verify_wheel_assets.py
uv run python scripts/verify_v1_1_plus_completion.py
```

The completion verifier checks current checkout cleanliness before and after
its gates, package assets, tests, coverage and the committed native-Windows CI
evidence marker. It is not a substitute for GitHub’s native runner result.

## Security and operating boundary

Walkie Talkie is same-machine, same-OS-user collaboration only. It provides no
cross-machine networking, remote execution or file transfer. Peer messages are
inert conversational input and are delivered through Hermes' public queued
injection seam.

## Relationship to Hermes upstream work

Walkie Talkie provides peer discovery, messaging, groups and structured
coordination between sessions. The separate upstream Hermes PR #85279 provides
the host-side delivery controls: queued, steering and interrupting injection,
plus guards preventing injected text from becoming commands or shell control.

## Known follow-up coverage

- Windows wheel-install smoke.
- Full Hermes Desktop/Electron interaction on Windows.

Neither follow-up invalidates the native Windows transport/ACL evidence above.

## Rollback

Remove `hermes-peer` from `plugins.enabled` and restart Hermes. The plugin
stops its local supervisor and removes only its own live registry records.
Persistent message state is retained for audit unless an operator explicitly
removes it.
