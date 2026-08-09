# Verification Record — exact candidates

All commands below run against the exact final candidate SHAs (P12 freeze):

- hermes-walkie-talkie: 6a5cf4cd72c2638912836cbe335047dc4a944797 (branch main)
- hermes-walkie-talkie-core: 5e7a111b3e748b0cfeb463f536ca52ad0db468fd (branch candidate/hermes-walkie-talkie-p1-20260809)

## Standalone repository (from /home/kensei/repos/hermes-walkie-talkie)

| Gate | Command | Result |
|---|---|---|
| Unit | `uv run pytest tests/unit -q` | 145 passed (final run) |
| Integration | `uv run pytest tests/integration -q` | 23 passed |
| E2E | `uv run pytest tests/e2e -q` | 12 passed; host-surface (4) additionally under PYTHONPATH=core worktree |
| Security | `uv run pytest tests/security -q` | 22 passed, 1 env skip |
| Full suite | `uv run pytest -q` | 247 passed, 4 skipped (2 chown env, 2 host-surface run separately) |
| Lint | `uv run ruff check .` | All checks passed |
| Types | `uv run ty check agent_peer hermes_peer` | All checks passed |
| Build | `uv build` | wheel dist/hermes_walkie_talkie-0.1.0rc1-py3-none-any.whl |
| Coverage | `uv run python scripts/coverage_gate.py` | PASS: 90.0% line; trust/delivery branch 86.7% (163/188) |
| Install | clone-style install into temp HERMES_HOME + wheel entry point | E2E-909/910 pass; entry point resolves |
| Demo | `uv run python scripts/demo_two_sessions.py` | PASS: discovery, send, receipt, reply, correlation |
| Verifier | `uv run python scripts/verify_goal_completion.py --plan <plan>` | PASS (exit 0) at final candidate |
| Clean | `git status --short` | empty |

## Hermes core candidate (from /home/kensei/worktrees/hermes-walkie-talkie-core)

| Gate | Command | Result |
|---|---|---|
| Injection tests | pytest tests/hermes_cli/test_plugin_message_injection.py tests/test_tui_gateway_inject.py tests/gateway/test_plugin_message_injection.py | 40 passed |
| Quick-command regression | pytest tests/cli/test_quick_commands.py | passed (5 exec/redaction/timeout tests) |
| Full suite (exact candidate) | pytest -q --continue-on-collection-errors | 145 failed (pre-existing baseline set + 1 env test) |
| Baseline comparison | same suite on baseline worktree @ 3f812796bb | candidate-only failures: 0 genuine (single diff = cron provider-pin, fails identically in isolation on both) |
| Clean | `git status --short` | empty |

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

## Completed-plan snapshot

- docs/review/completed-plan.md SHA-256: c16e8b6eb1d36ec881ac934bf145a19b489d0ba91dd2d851cc63cb2ade28c9f3
- Copied from the live plan after the final verifier pass (PILOT-1208 two-pass finalisation).
