#!/usr/bin/env python3
"""Deterministic V1.1+ completion verifier (P11.8/P11.12).

This script decides COMPLETE/PARTIAL/BLOCKED from REAL evidence only:

- plan checkboxes parsed from the plan markdown (single source of truth
  for the phase list),
- git ancestry + exact HEAD SHA of the standalone worktree,
- clean-worktree checks for the standalone and frozen core worktrees,
- package assets present in the wheel build inputs,
- full test suite exit code (real run, not a recorded number),
- coverage gate exit code,
- native Windows evidence status (parsed from WINDOWS_EVIDENCE.md and
  cross-checked against the platform; on a Linux rig it is BLOCKED by
  policy and can never be COMPLETE).

Exit codes: 0 = COMPLETE, 2 = PARTIAL (blocked/known gaps), 3 = FAIL.
Every PASS/FAIL line prints a concrete check and the value it saw —
no Markdown-string placebo verdicts.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLAN = Path("/home/kensei/.hermes/plans/2026-08-11_030133-hermes-walkie-talkie-v1-1-plus.md")
FROZEN_CORE_WORKTREES = [
    Path("/home/kensei/worktrees/hermes-walkie-talkie-core-v1-1"),
    Path("/home/kensei/worktrees/hermes-walkie-talkie-core-v1-pr"),
]
LOCKED_CORE_SHA = "2a853f8681e5aecd8b7059272598c33c17bf9370"
WINDOWS_EVIDENCE = REPO / "docs" / "review" / "WINDOWS_EVIDENCE.md"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False,
    ).stdout.strip()


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=1800)


def parse_plan_phases() -> dict[str, bool]:
    """Checkbox state of every `- [ ] **P<n>.<m>**` sub-goal line."""
    text = PLAN.read_text(encoding="utf-8")
    phases: dict[str, bool] = {}
    for m in re.finditer(r"- \[([ xX])\]\s+\*\*(P\d+\.\d+)\*\*", text):
        phases[m.group(2)] = (m.group(1).lower() == "x")
    return phases


def main() -> int:
    print(f"VERIFIER: {REPO}")
    print(f"HEAD: {git(REPO, 'rev-parse', 'HEAD')}")

    # 1. Plan checkboxes (P0.x..P11.x).
    phases = parse_plan_phases()
    total = len(phases)
    checked = sum(1 for done in phases.values() if done)
    unchecked = [p for p, done in phases.items() if not done]
    # Known-blocked/pending gaps that do NOT fail the verifier:
    # native Windows release evidence (policy-blocked on this rig),
    # the Windows-home wheel-install leg, and the review-packet steps
    # that run after this verifier's first pass.
    ALLOWED_UNTICKED = {
        "P9.2", "P9.4", "P9.9",           # native Windows release evidence — BLOCKED
        "P10.5",                           # Windows-home leg blocked; Linux leg done
        "P11.9", "P11.10", "P11.11", "P11.12",  # review packet + independent review
    }
    unexpected = [p for p in unchecked if p not in ALLOWED_UNTICKED]
    check("plan-checkboxes-present", total >= 40, f"{total} sub-goals found")
    check("plan-checkboxes-checked", not unexpected, f"unexpectedly unchecked {unexpected or 'none'}")
    print(f"   plan: {checked}/{total} checked; blocked/pending: {sorted(set(unchecked))}")

    # 2. Standalone clean worktree.
    dirty = git(REPO, "status", "--porcelain")
    check("standalone-clean", not dirty, f"dirty files {dirty.splitlines() or 'none'}")

    # 3. Frozen core worktrees clean + at locked SHA.
    for wt in FROZEN_CORE_WORKTREES:
        if not wt.exists():
            check(f"core-{wt.name}-exists", False, f"{wt} missing")
            continue
        sha = git(wt, "rev-parse", "HEAD")
        dirty = git(wt, "status", "--porcelain")
        check(f"core-{wt.name}-sha", sha == LOCKED_CORE_SHA, f"{sha} (locked {LOCKED_CORE_SHA})")
        check(f"core-{wt.name}-clean", not dirty, f"dirty files {dirty.splitlines() or 'none'}")

    # 4. Package assets on disk (wheel build inputs).
    for asset in [
        "hermes_peer/assets/desktop/plugin.js",
        "hermes_peer/assets/desktop/style.css",
        "dashboard/manifest.json",
    ]:
        p = REPO / asset
        check(f"asset-{asset}", p.exists() and p.stat().st_size > 0, str(p))

    # 5. Real full suite.
    import os

    env = dict(os.environ)
    env["HERMES_CORE_ROOT"] = str(Path("/home/kensei/worktrees/hermes-walkie-talkie-core-remediation-r2"))
    env["HERMES_PYTHON"] = "/home/kensei/repos/KenseiAgent/.venv/bin/python"
    suite = run(
        [sys.executable, "-m", "pytest", "-q", "--no-header"],
        cwd=REPO,
    )
    last = (suite.stdout or "").strip().splitlines()[-1:] + (suite.stderr or "").strip().splitlines()[-1:]
    check("full-suite", suite.returncode == 0, f"rc={suite.returncode} {last}")

    # 6. Coverage gate (real run).
    gate = run([sys.executable, "scripts/coverage_gate.py"], cwd=REPO)
    gate_tail = (gate.stdout or "").strip().splitlines()[-2:]
    check("coverage-gate", gate.returncode == 0, f"rc={gate.returncode} {gate_tail}")

    # 6b. Post-gate worktree cleanliness: the suite + coverage gate must
    # not mutate tracked files (e.g. regenerate uv.lock, rewrite assets).
    # The pre-gate check alone cannot catch mutation introduced by the
    # gates themselves.
    dirty_after = git(REPO, "status", "--porcelain")
    check("post-gate-clean", not dirty_after, f"dirty files after gates {dirty_after.splitlines() or 'none'}")
    if dirty_after:
        print("POST-GATE DIRTY FILES:")
        for line in dirty_after.splitlines():
            print(f"  {line}")

    # 7. Windows native evidence status.
    windows_ok = False
    windows_detail = "BLOCKED (no native Windows runner on this rig)"
    if sys.platform == "win32":
        if WINDOWS_EVIDENCE.exists():
            text = WINDOWS_EVIDENCE.read_text(encoding="utf-8")
            windows_ok = "NATIVE PROOF COMPLETE" in text
            windows_detail = "native proof marker found"
        check("windows-native-evidence", windows_ok, windows_detail)
    else:
        check("windows-native-evidence", False, windows_detail)

    # 8. Anti-placebo: no Markdown-parser verdicts can flip this result.
    # (This script itself is the deterministic gate; the review packet is
    # for humans and does not affect exit code.)

    fails = [n for n, ok, _ in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    if fails:
        print("FAILED:", ", ".join(fails))
        # Windows native release evidence is policy-BLOCKED on non-win32:
        # when it is the ONLY failing check the verdict is PARTIAL (2),
        # never FAIL (3) — the implementation is complete, the release
        # evidence is blocked (plan P10.9).
        only_windows = all("windows-native" in f for f in fails)
        if only_windows:
            print("VERDICT: PARTIAL — IMPLEMENTED, WINDOWS RELEASE EVIDENCE BLOCKED")
            return 2
        print("VERDICT: FAIL")
        return 3
    print("VERDICT: COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
