# V1.1+ Execution Ledger

> Live execution record for the Hermes Walkie Talkie V1.1+ plan
> Plan: `/home/kensei/.hermes/plans/2026-08-11_030133-hermes-walkie-talkie-v1-1-plus.md`
> Started: 11 August 2026

## Publication precondition (P0.1) — verified 11 Aug 2026

| ID | Evidence | Result |
|----|----------|--------|
| PUB-01 | `https://api.github.com/repos/Sahil-SS9/hermes-walkie-talkie` | HTTP 200 — repo exists |
| PUB-02 | `gh api repos/Sahil-SS9/hermes-walkie-talkie/commits/main` | `f6d45194e3a906c13a2449805976d4e151430437` — exact |
| PUB-07 | `gh api repos/Sahil-SS9/hermes-agent/branches/feat/hermes-peer-delivery-seam-v1` | `2a853f8681e5aecd8b7059272598c33c17bf9370` — exact |
| PUB-08/09 | `gh api repos/NousResearch/hermes-agent/pulls/83661` | state=open, draft=true, base=`2cdb30a474d76cca9eb61714d889c18f493aa7fc`, head=`2a853f8681e5aecd8b7059272598c33c17bf9370`, mergeable_state=blocked (checks pending) |
| PUB-10 | `https://api.github.com/repos/NousResearch/hermes-agent/issues/comments/5248719563` | id=5248719563 exists |

## Successor worktrees (P0.3/P0.4) — verified 11 Aug 2026

- Standalone: `/home/kensei/worktrees/hermes-walkie-talkie-v1-1`, branch `feat/hermes-walkie-talkie-v1-1`, HEAD `f6d45194e3a906c13a2449805976d4e151430437`, porcelain clean
- Core: `/home/kensei/worktrees/hermes-walkie-talkie-core-v1-1`, branch `feat/hermes-peer-v1-1`, HEAD `2a853f8681e5aecd8b7059272598c33c17bf9370`, porcelain clean
- Frozen V1 standalone (r2): `/home/kensei/worktrees/hermes-walkie-talkie-remediation-r2` @ `f6d45194e3a906c13a2449805976d4e151430437` — clean, untouched
- Frozen V1 core (r2): `/home/kensei/worktrees/hermes-walkie-talkie-core-remediation-r2` @ `69631bd75cc212fc3b254c8e1b5d87e7ab2a9b86` — clean, untouched

## Baseline matrix (P0.6) — archived `docs/review/V1_BASELINE.md`

- Command: `.venv/bin/python -m pytest -q` in standalone worktree @ f6d45194
- Result: `403 passed, 4 skipped` (skips: 2 missing hermes-core imports — expected standalone; 2 chown-ineligible)
- Runner: Python 3.12.3, uv 0.11.28, Linux
- Core affected baseline @ 2a853f86 (clean draft-PR head, `.venv/bin/python -m pytest`): `590 passed` across the 7 affected files
- PLAN PATH DEVIATION: plan lists `tests/hermes_cli/test_session_boundary_hooks.py`; actual path in this core tree is `tests/cli/test_session_boundary_hooks.py`. All other listed paths exist.

## Windows native gate note

No native Windows execution path exists on this rig (checked: wine, /mnt/c, VM — none). Remote CI push is forbidden by NG-13/ACC-22. Per plan P10.9/ACC-22, Windows-native gates are recorded BLOCKED with exact missing evidence; final status will be `PARTIAL` (`IMPLEMENTED — WINDOWS RELEASE EVIDENCE BLOCKED`), never COMPLETE. No mock substitutes security evidence (G5.8, P0 gate).

## Execution log

| Phase | Commit | Result |
|-------|--------|--------|
| P0 | `fa470e8` (docs, no code) | PUB verified; baseline archived; ADRs + spike reports written |
| P1 | `9f12f72` | Backend-neutral extraction: 10 conformance + 17 backend/path tests new; full suite 430 passed/4 skipped (baseline 403); ruff clean; ty clean; coverage gate PASS 91.6% |
| P2 | `001bf49` | Native Windows backend: SID/DACL named pipes via pywin32 (optional extra); WindowsPathBackend under %LOCALAPPDATA%; 18 native-gated tests written (skip on Linux with explicit reason — never green evidence); fail-closed platform checks on Linux; ruff/ty clean; coverage gate PASS 91.6%; native gate BLOCKED on this rig |
| P3 | `5c5385d` | Stable agent identity + V2 protocol: PeerRecord agent_id/protocols/capabilities; ReceiptState incompatible/ambiguous; Surface.DESKTOP; capabilities.py negotiation (highest-mutual, fail-closed); protocol_v2.py strict typed payloads; resolve_agent deterministic routing (pinned→primary→single→ambiguous); agent_identity.py owner-only persistence in HERMES_HOME (ephemeral when no real home — tests never mutate ~/.hermes); sessions.py V2 advertisement; store v2 migration (idempotent, old rows readable as V1, readonly-safe). 49 new tests; full suite 487 passed/4+18 skipped; ruff/ty clean; coverage gate PASS 91.3% |
| P4 | `5d59992` | Persistent groups + bounded broadcasts: groups/group_members/broadcasts/broadcast_children tables (schema v3, idempotent migration); GroupStore CRUD with optimistic revision, unique normalised names, owner fence, member caps (default 32/hard 128); BroadcastEngine persist-parent-first, deterministic child IDs from (broadcast_id, agent_id, peer_id), atomic created→in_flight single-writer gate (concurrent duplicate broadcasters converge), bounded concurrency, explicit partial results, sender self-exclusion. 26 new tests incl. real-runtime integration + property idempotency; full suite 513 passed; ruff/ty clean; coverage gate PASS 91.5% |
| P5 | `4477e21` | Structured request/reply workflows: pure transition decision table (workflows.py, impossible/stale transitions rejected, advisory cancel, terminal frozen); Request aggregate + schema v4 (requests/request_events, idempotent migration, NULL-key semantics so keyless requests coexist); RequestStore create/status/transition/expire with (sender,key) idempotency returning original; session manager create_request/status/respond/cancel/expire with recipient-only respond; `<peer_request>` inert conversational marker; request tools (create/status/respond/cancel); REAL two-Hermes E2E drives create→delivered→accept→progress→complete through the model pipeline. 38 new tests; full suite 551 passed; ruff/ty clean; coverage gate PASS 90.1%. Test-isolation fix: fixtures now pin AGENT_PEER_STATE_DIR (integration tests never touch real ~/.local/state) |
| P6 | `c5ea5d7` | V1.1 operations: content-free MetricsRegistry (counts/latency/failure-reason/held-depth/stale-events; no content params by structural gate); bounded EventBroker (slow consumers dropped, client cap); health_snapshot with actionable remedies; stale alerts with debounce + exact-instance fence; session manager instruments _on_inbound (delivery/held metrics + events), doctor() expanded to full health snapshot + metrics, metrics/events exposed for Desktop; PeerConfig ceilings validated within hard bounds (group_cap≤128, fanout≤64, TTL bounds, event_clients≤256). 34 new tests; full suite 582 passed; ruff/ty clean; coverage gate PASS 90.4% |
| P7 | `4f77e5b` | Hermes tools/commands/install UX: group tools (list/manage/broadcast); request tools (create/status/respond/cancel); V1 tools preserved with **kwargs dispatcher metadata; slash commands peer-groups/peer-group/peer-broadcast/peer-request; CLI subcommands groups/group/broadcast/request/desktop; `hermes peer desktop install|status|remove` with bundled plugin.js asset (explicit install only, G6.9); tool-schema budget gate (10 tools, <4KiB aggregate, hermes-peer-scoped); multi-session ambiguity fails closed (P7.6); alias-is-display-only membership proof. 35 new tests; full suite 617 passed; ruff/ty clean; coverage gate PASS 90.2% |
| P8 | `2c0686c` | First-class Hermes Desktop plugin: dashboard/manifest.json + FastAPI plugin_api at /api/plugins/hermes-peer (health/metrics/peers/groups+members/broadcast outcomes/inbox/requests+respond, /events WebSocket via canonical _ws_auth_ok gate, always-frame heartbeat); desktop/ React+TS source (api.ts typed wrappers, store.ts profile-scoped refresher + bounded activity ring, PeerPanel tabs Peers/Groups/Inbox/Requests/Health, statusBar+secondarySidebar contributions); vite build externalizes @hermes/plugin-sdk (loader-injected) producing compiled plugin.js + style.css copied into hermes_peer/assets/desktop (wheel package-data: dashboard + assets shipped, ACC-17); `hermes peer desktop install` now copies the full compiled bundle (plugin.js + style.css); G6.9 no-auto-install structural test; sdk-stub.d.ts for standalone typecheck (local type stub mirrors consumed PluginContext surface). 15 new Python tests + 7 vitest; full suite 629 passed; ruff/ty clean; coverage gate PASS 90.2% |
| P9 | `1a13098` | Cross-platform real-process E2E: REAL two-Hermes broadcast E2E (create group → add member by stable agent_id → broadcast through real deferred search→describe→call dispatch; child reaches B's store via the real transport; callable-script support added to fake_model_server so a runtime-discovered group_id threads through deferred dispatch); REAL desktop-surface E2E (a real process opens a desktop session, a second real process observes the peer with surface=desktop); busy-target queue-only tests (delivery always uses host mode=queue, HELD on refusal, dedup at most-once); trust-path validation branch tests (every fail-closed model rejection). Two real drift fixes locked by tests: (1) `_surface_of("desktop")` collapsed to tui so Surface.DESKTOP was never advertised — desktop now preserved (4 new unit tests); (2) BroadcastEngine summary omitted the `held` delivered state even though the failure gate counted it — summary now surfaces `held` (P9.5 evidence). P9.2/P9.4/P9.9 stay native-gated on Windows (BLOCKED on this rig); P9.10 uses the deterministic fake model server and reports that limit. 20 new tests; full suite 649 passed; ruff/ty clean; coverage gate PASS 90.5% |
| P10 | `836ae17` | CI/packaging/docs: ci.yml expanded to ubuntu/macos/windows × Python 3.11–3.13 + coverage gate step + wheel-asset verify step + install-from-wheel smoke (POSIX) + `native-windows` job running the native-gated suites on windows-latest so skips become real green evidence (workflow prepared locally; pushing/starting remote CI still requires approval); new `tests/e2e/test_windows_native.py` (backend selection, real two-process named-pipe exchange P9.2, wrong-user DACL denial P9.9); `scripts/verify_wheel_assets.py` (ACC-17: Python packages + plugin.yaml + dashboard manifest/plugin_api + compiled Desktop plugin.js/style.css present in wheel — verified locally PASS); wheel built + installed into a disposable venv + doctor/desktop-install smoke PASS (P10.5 POSIX leg); docs: architecture/security/compatibility extended for V1.1; new windows.md, groups-and-broadcasts.md, request-workflows.md, desktop.md, operations.md, upgrade-v1-to-v1-1.md; README/CHANGELOG updated; P10.8 limitations documented (local same-user only, flat groups, advisory cancel, Windows evidence BLOCKED); P10.9 no tag/publish/activate. Full suite 649 passed; ruff/ty clean; coverage gate PASS 90.6% |
| P11.1-11.2 | `85e68e1` | Expanded coverage gate to all 28 V1.1 trust modules + `--cov=dashboard`; adversarial branch tests (posix backend 9, protocol_v2 10, metrics/health 5, groups 11, requests 3, v2 tools 9, desktop install 4, dashboard API 13, CLI 16, sessions 8); gate PASS 92.6% line / ≥85% branch on expanded set |
| P11.6 | `968724b` | Anti-placebo: removed `or True` fake assertion in test_desktop_no_auto_install.py; ruff cleanup |
| P11.8-11.9 | `80f8aca` | Deterministic verifier `scripts/verify_v1_1_plus_completion.py` (exit 0/2/3, real evidence only, rejects placebo + stale pairs); review packet: HANDOFF, VERIFICATION, DEVIATIONS, SECURITY, WINDOWS_EVIDENCE (BLOCKED), DESKTOP_EVIDENCE, completed-plan |

## Final verifier pass (P11.12)

At HEAD `80f8aca`: 12/13 checks pass; the only failing check is
`windows-native-evidence` (BLOCKED — no native Windows runner on this rig,
policy per plan P10.9/ADR-0005). Verdict: **PARTIAL — IMPLEMENTED,
WINDOWS RELEASE EVIDENCE BLOCKED** (exit 2). Full suite 720 passed /
25 skipped (3 native-Windows + 2 chown env); coverage gate PASS 92.7%.

## P11.3 adversarial probe evidence

Against final SHA `b00e5e7`: 38 passed / 14 skipped across
`test_broadcast_idempotency` (property: concurrent fan-out converges on
exactly one child per recipient), `test_workflow_transitions` (every
legal/illegal transition), `test_request_workflow` (full
queued→accepted→progress→completed timeline), `test_busy_target_queue_only`
(HELD/queue-only delivery), `test_windows_owner_boundary` +
`test_windows_backend` (SID/DACL contract; native-gated), 
`test_desktop_plugin_install`, `test_dashboard_api` (503/404/WS).
All 14 skips carry the explicit `NATIVE WINDOWS GATE` reason — no silent
disablement.

## Remaining (post-goal, external)

- P11.10/P11.11: fresh independent read-only adversarial review against
  the exact final SHAs, using the attack checklist in HANDOFF.md; findings
  recorded in `docs/review/INDEPENDENT_REVIEW.md`.
- P11.12 second pass after review; then tick P11.9–11.12 and re-run the
  verifier (still PARTIAL until a Windows runner provides native proof).

## Environment facts

- `uv sync --group dev` creates worktree-local venv; import resolves to worktree (verified)
- Core worktree has no venv; hermes-agent core is not pip-editable — per phased-plan-execution skill, run core tests with canonical `.venv/bin/python -m pytest` from inside the worktree (CWD-relative imports resolve hermes_cli/gateway), or `uv run` after sync
- Core desktop runtime-loader contract at `apps/desktop/src/contrib/runtime-loader.ts`; disk plugins live at `<HERMES_HOME>/desktop-plugins/<name>/plugin.js`
- Dashboard plugin contract: `plugins/<name>/dashboard/manifest.json` + `dashboard/plugin_api.py`, mounted at `/api/plugins/<name>/`, session-token auth via `web_server.auth_middleware`
