# Hermes Walkie Talkie V1.1+ — Independent Review Handoff

Status: UNRELEASED local review candidate. Not pushed, not published,
not activated anywhere. Post-goal: Sahil and/or an independent reviewer
verify the EXACT candidates below; findings then decide remediation,
upstream PR submission, release and live pilot.

## Exact candidates

| Repository | Branch | Commit | Clean |
|---|---|---|---|
| Hermes Walkie Talkie (standalone) | feat/hermes-walkie-talkie-v1-1 | 968724b7283fc9cd448d22a89c9728da29ce1cc6 | yes |
| Hermes core candidate (clean PR worktree) | feat/hermes-peer-v1-1 (draft PR #83661) | 2a853f8681e5aecd8b7059272598c33c17bf9370 | yes |

The frozen core worktrees `hermes-walkie-talkie-core-v1-1` and
`hermes-walkie-talkie-core-v1-pr` both sit at the locked clean draft-PR
head `2a853f86`. Canonical Hermes checkout (`/home/kensei/repos/KenseiAgent`):
NOT modified by this goal.

## What to verify (read-only first)

1. `git status --short` is empty in the standalone and both frozen core
   worktrees; `git rev-parse HEAD` matches the table.
2. From the standalone repo:
   - `uv run pytest -q` (full suite)
   - `uv run ruff check .`, `uv run ty check agent_peer hermes_peer dashboard`
   - `uv run python scripts/coverage_gate.py` (90% line / 85% branch over
     the expanded V1.1 trust module set)
   - `uv run python scripts/verify_wheel_assets.py`
   - `uv run python scripts/verify_v1_1_plus_completion.py --plan <plan>`
     (deterministic; exit 0 only at the true final candidate, exit 2 for
     known-blocked Windows evidence, never a Markdown verdict)
3. Security: `tests/security/` suite (permissions, symlink races, control
   injection, fuzzing, flood, concurrency, storage failure, no-TCP, log
   redaction, static audits, Windows owner boundary, busy-target queue-only).
4. Windows: see `docs/review/WINDOWS_EVIDENCE.md` — native release evidence
   is BLOCKED on this rig and must stay BLOCKED.
5. Desktop: see `docs/review/DESKTOP_EVIDENCE.md` — bundle ships in the
   wheel; live activation inside Hermes Desktop is out of scope here.

## Key V1.1 additions (standalone)

- Stable per-profile `agent_id` (owner-only UUID in HERMES_HOME),
  protocol negotiation (`agent-peer/1` unchanged, V2 typed payloads),
  deterministic agent→peer routing.
- Persistent groups (schema v3) with ownership/revision/caps; bounded
  broadcasts with an atomic single-writer gate and per-recipient children.
- Structured request workflows (schema v4): created→queued→accepted→
  in_progress→completed|failed|refused|cancelled|expired; idempotency
  keys, correlation, ordered events.
- Operations observability: content-free metrics, local events, health
  snapshots, doctor/status remediation.
- V2 tools + slash commands, tool-schema budget gate, CLI desktop install.
- Hermes Desktop plugin (React panel + FastAPI router + WS events) and
  dashboard manifest; wheel ships all assets.
- Windows named-pipe backend: fail-closed SID/DACL implementation,
  native-gated tests, evidence BLOCKED.

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

## Independent reviewer attack checklist (P11.11)

The reviewer must explicitly attack every original V1 blocker plus the
V1.1 boundaries, against the EXACT final SHAs in the table above
(read-only; record findings in `docs/review/INDEPENDENT_REVIEW.md`):

1. **V1 blockers**: cross-process discovery; same-UID enforcement;
   symlink/fence races; control injection; flood/rate limits; storage
   failure; shutdown/teardown; no cross-machine networking.
2. **Windows (new)**: named-pipe SDDL/DACL owner-boundary; wrong-user
   denial; native backend selection; the fail-closed `NotImplementedError`
   guard; Windows-home wheel install.
3. **Groups (new)**: ownership fence; unique-name normalisation; caps;
   optimistic revision; stale membership.
4. **Broadcasts (new)**: atomic single-writer gate; bounded fan-out;
   sender self-exclusion; per-recipient child ids; partial-failure
   semantics; held/queue-only delivery.
5. **Workflows (new)**: every legal/illegal transition; idempotency-key
   dedup; deadline/expiry; advisory cancellation; state-event ordering.
6. **Desktop (new)**: no-auto-install (G6.9); wheel asset integrity;
   dashboard API auth boundary; WS upgrade gate; content-free metrics;
   profile scoping.
7. **Verifier integrity (P11.12)**: the completion verifier must not
   accept a stale candidate pair, a mismatched SHA, a dirty worktree,
   or any Markdown/parser placebo verdict; Windows evidence must stay
   BLOCKED on non-win32.
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
