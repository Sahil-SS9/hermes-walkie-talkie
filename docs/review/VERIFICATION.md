# Verification Record — exact candidates

All commands below run against the exact final candidate SHAs (P12 freeze):

- hermes-walkie-talkie: __STANDALONE_SHA__ (branch main)
- hermes-walkie-talkie-core: __CORE_SHA__ (branch candidate/hermes-walkie-talkie-p1-20260809)

## Standalone repository (from /home/kensei/repos/hermes-walkie-talkie)

| Gate | Command | Result |
|---|---|---|
| Unit | `uv run pytest tests/unit -q` | __TBD__ |
| Integration | `uv run pytest tests/integration -q` | __TBD__ |
| E2E | `uv run pytest tests/e2e -q` | __TBD__ (host-surface tests additionally under PYTHONPATH=core worktree) |
| Security | `uv run pytest tests/security -q` | __TBD__ |
| Full suite | `uv run pytest -q` | __TBD__ |
| Lint | `uv run ruff check .` | __TBD__ |
| Types | `uv run ty check agent_peer hermes_peer` | __TBD__ |
| Build | `uv build` | __TBD__ |
| Coverage | `uv run python scripts/coverage_gate.py` | __TBD__ (target: >=90% line, >=85% trust/delivery branch) |
| Install | clone-style install into temp HERMES_HOME + wheel entry point | __TBD__ |
| Demo | `uv run python scripts/demo_two_sessions.py` | __TBD__ |
| Verifier | `uv run python scripts/verify_goal_completion.py --plan <plan>` | __TBD__ (must exit 0) |
| Clean | `git status --short` | __TBD__ (must be empty) |

## Hermes core candidate (from /home/kensei/worktrees/hermes-walkie-talkie-core)

| Gate | Command | Result |
|---|---|---|
| Injection tests | pytest tests/hermes_cli/test_plugin_message_injection.py tests/test_tui_gateway_inject.py tests/gateway/test_plugin_message_injection.py | __TBD__ (40 tests) |
| Quick-command regression | pytest tests/cli/test_quick_commands.py | __TBD__ |
| Full suite (exact candidate) | pytest -q --continue-on-collection-errors | __TBD__ fails (pre-existing baseline collection errors) |
| Baseline comparison | same suite on baseline worktree @ 3f812796bb | candidate-only failures: __TBD__ (must be 0) |
| Clean | `git status --short` | __TBD__ (must be empty) |

Note on the full-suite: the baseline commit itself carries pre-existing
collection errors and failures (verified identical on the pristine base);
the gate is ZERO candidate-only failures versus the exact base.

## No-go audit

Release no-go checklist (plan section 10): all boxes remain unchecked.
observed_no_go_blockers: 0.

## Producer QA audit (SEC-1011)

The security, concurrency, recovery and release gates were rerun from a
clean state by the single executor and recorded in the plan ledger. This is
producer evidence, not a substitute for the post-goal independent review.
