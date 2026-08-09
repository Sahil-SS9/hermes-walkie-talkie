# Hermes Walkie Talkie — Independent Review Handoff

Status: UNRELEASED local review candidate (v0.1.0-rc1). Not pushed, not
published, not activated anywhere. Post-goal: Sahil and/or an independent
reviewer verify the EXACT candidates below; findings then decide any
remediation, upstream PR submission, release and live pilot.

## Exact candidates

| Repository | Branch | Commit | Clean |
|---|---|---|---|
| Hermes Walkie Talkie (standalone) | main | 6a5cf4cd72c2638912836cbe335047dc4a944797 | yes |
| Hermes core candidate (isolated worktree) | candidate/hermes-walkie-talkie-p1-20260809 | 5e7a111b3e748b0cfeb463f536ca52ad0db468fd | yes |

Canonical Hermes checkout (`/home/kensei/repos/KenseiAgent`): NOT modified by
this goal (its HEAD may have moved externally; unrelated dirty files were
untouched). The Hermes core candidate has NOT been merged into it.

## What to verify (read-only first)

1. `git status --short` is empty in both repositories above.
2. `git rev-parse HEAD` matches the table.
3. From the standalone repo:
   - `uv run pytest -q` (full suite; host-surface E2E additionally under
     PYTHONPATH=/home/kensei/worktrees/hermes-walkie-talkie-core)
   - `uv run ruff check .`, `uv run ty check agent_peer hermes_peer`,
     `uv build`
   - `uv run python scripts/coverage_gate.py` (90% line / 85% trust-delivery
     branch)
   - `uv run python scripts/verify_goal_completion.py --plan <plan>` (exit 0
     only at the true final candidate)
   - `uv run python scripts/demo_two_sessions.py` (two-session demo)
4. From the core worktree (with the canonical venv python):
   - the 40 P1 injection tests and `tests/cli/test_quick_commands.py`
   - full-suite comparison: candidate failures minus baseline failures = 0
     (baseline worktree at 3f812796bb)
5. Security: tests/security suite (permissions, symlink races, control
   injection, fuzzing, flood, concurrency, storage failure, no-TCP, log
   redaction, static audits).

## Changed paths (Hermes core candidate)

- `hermes_cli/plugins.py` — additive `inject_message` (mode/target_session)
  + headless injection-router registry
- `cli.py` — public `HermesCLI.inject_message`; `_injected_input`
  conversational queue (inert-control)
- `tui_gateway/server.py` — `inject_external_message` + router registration
- `gateway/run.py` — `inject_plugin_message` (per-plugin gate, stored-route
  reuse, busy FIFO) + `non_control` command gate
- `gateway/platforms/base.py` — `MessageEvent.non_control` field
- `website/docs/user-guide/features/plugins.md` — seam documentation
- New tests: tests/hermes_cli/test_plugin_message_injection.py,
  tests/test_tui_gateway_inject.py,
  tests/gateway/test_plugin_message_injection.py

## Changed paths (standalone repository)

- `agent_peer/` — protocol, paths, identity, registry, presence, transport,
  runtime, store, policy (13 modules)
- `hermes_peer/` — config, sessions, delivery, tools, commands, plugin
- `skills/peer-messaging/SKILL.md`, `scripts/` (verifier, coverage gate,
  demo), `docs/` (ADR-0001..0003, architecture, protocol, security,
  troubleshooting, compatibility, review), `tests/` (unit, integration,
  e2e, security, property), CI workflow, packaging

## Threat boundary

Peer messaging is a same-OS-user trust boundary: any process of the same
user may register, discover and message peers. Controls: owner-only paths,
same-UID socket checks, untrusted `<peer_message>` boundary, inert control
text, bounded payloads/rates/capacity, explicit receipts. See
docs/security.md.

## No-go blockers observed

observed_no_go_blockers: 0

## Rollback

- Hermes core: remove/delete the isolated worktree branch; nothing was
  merged into the canonical checkout.
- Plugin: remove `hermes-peer` from `plugins.enabled` and restart; the
  plugin stops its supervisor and removes only its own registry records.
  Persistent message state remains for audit unless explicitly purged
  (never deleted automatically).

## Upstream patch instructions

See docs/review/upstream-pr-draft.md — a local commit series plus a draft PR
description reconciled with NousResearch/hermes-agent#81885 and open PRs
#64436, #70406, #80920. Do not submit until Sahil authorises.

## Goal-budget restoration (PILOT-1210)

The pre-goal value of `goals.max_turns` was recorded in
`/home/kensei/.hermes/state/hermes-walkie-talkie-goal-max-turns.before`.
Restore with:

    hermes config set goals.max_turns <previous-value>
