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

## Windows native gate note

No native Windows execution path exists on this rig (checked: wine, /mnt/c, VM — none). Remote CI push is forbidden by NG-13/ACC-22. Per plan P10.9/ACC-22, Windows-native gates are recorded BLOCKED with exact missing evidence; final status will be `PARTIAL` (`IMPLEMENTED — WINDOWS RELEASE EVIDENCE BLOCKED`), never COMPLETE. No mock substitutes security evidence (G5.8, P0 gate).

## Execution log

| Phase | Commit | Result |
|-------|--------|--------|
| P0 | (docs, no code) | PUB verified; baseline archived; ADRs + spike reports written |

## Environment facts

- `uv sync --group dev` creates worktree-local venv; import resolves to worktree (verified)
- Core worktree has no venv; hermes-agent core is not pip-editable — per phased-plan-execution skill, run core tests with canonical `.venv/bin/python -m pytest` from inside the worktree (CWD-relative imports resolve hermes_cli/gateway), or `uv run` after sync
- Core desktop runtime-loader contract at `apps/desktop/src/contrib/runtime-loader.ts`; disk plugins live at `<HERMES_HOME>/desktop-plugins/<name>/plugin.js`
- Dashboard plugin contract: `plugins/<name>/dashboard/manifest.json` + `dashboard/plugin_api.py`, mounted at `/api/plugins/<name>/`, session-token auth via `web_server.auth_middleware`
