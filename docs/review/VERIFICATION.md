# Verification Record — exact candidates (V1.1+)

All commands below run against the exact final candidate SHA (P11.7 freeze):

- hermes-walkie-talkie standalone: `968724b7283fc9cd448d22a89c9728da29ce1cc6`
  (branch `feat/hermes-walkie-talkie-v1-1`) — the commit at which every
  gate below was run and passed; later commits in this packet may exist
  only for the packet's own evidence/docs.
- Hermes core candidate: `2a853f8681e5aecd8b7059272598c33c17bf9370`
  (clean draft-PR head; frozen worktrees `core-v1-1` and `core-v1-pr`).

## Standalone repository (from /home/kensei/worktrees/hermes-walkie-talkie-v1-1)

| Gate | Command | Result |
|---|---|---|
| Full suite | `.venv/bin/python -m pytest -q` (HERMES_CORE_ROOT=core-remediation-r2) | 684+ passed, 25 skipped (3 native-Windows + 2 chown env) |
| Lint | `.venv/bin/python -m ruff check .` | All checks passed |
| Types | `.venv/bin/python -m ty check agent_peer hermes_peer dashboard` | All checks passed |
| Coverage | `.venv/bin/python scripts/coverage_gate.py` | PASS: 92.5% line (3366/3637); expanded V1.1 trust branch ≥85% |
| Wheel assets | `.venv/bin/python scripts/verify_wheel_assets.py` | ALL ASSETS PRESENT (8 required paths) |
| Wheel install (Linux) | uv pip install dist/*.whl into disposable venv + doctor/desktop smoke | PASS |
| Verifier | `.venv/bin/python scripts/verify_v1_1_plus_completion.py` | exit 2 = PARTIAL (Windows evidence BLOCKED by policy, all other checks PASS) |
| Clean | `git status --short` | empty |

Phase gates (committed, verified at commit time): P0 `fa470e8`, P1 `9f12f72`,
P2 `001bf49`, P3 `5c5385d`, P4 `5d59992`, P5 `4477e21`, P6 `c5ea5d7`,
P7 `4f77e5b`, P8 `2c0686c`, P9 `1a13098`, P10 `836ae17`, P11 `85e68e1` +
`968724b`.

## Native Windows evidence

See `docs/review/WINDOWS_EVIDENCE.md`. Status: BLOCKED. The verifier
hard-fails `windows-native-evidence` on non-win32; no Linux claim can
flip it.

## Hermes core candidate

The core worktree is unchanged at the locked draft-PR head `2a853f86`
(clean, 590+ passed at capture). The standalone V1.1 suite runs against
the core-remediation-r2 worktree for host-surface E2E, matching the V1
baseline pattern.

## No-go audit

Release no-go checklist (plan section 10): all boxes remain unchecked.
Nothing pushed, merged, published, tagged, installed or activated.

## Producer QA audit (P11)

The security, concurrency, recovery, coverage-expansion and release gates
were rerun from a clean state by the single executor and recorded in the
execution ledger. This is producer evidence, not a substitute for the
post-goal independent review (P11.10–P11.12).
