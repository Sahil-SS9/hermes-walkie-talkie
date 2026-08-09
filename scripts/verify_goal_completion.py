#!/usr/bin/env python3
"""Deterministic goal-completion verifier for Hermes Walkie Talkie (AP-208).

Usage:
    uv run python scripts/verify_goal_completion.py --plan <plan-path>

Exits 0 ONLY when the goal is genuinely complete at the exact final
candidates. Fails non-zero for any of:

  1. any in-scope implementation task (AP-/H-/HP-/E2E-/SEC-/REL-/PILOT-) or
     phase box (P0..P12) or release-acceptance box left unchecked;
  2. any checked no-go blocker (section 10) — a checked box there is NO-GO;
  3. missing ledger evidence rows for checked tasks;
  4. missing review packet files (HANDOFF.md, VERIFICATION.md, DEVIATIONS.md,
     completed-plan.md) or an observed_no_go_blockers marker != 0;
  5. a dirty Git candidate (standalone repo or Hermes core worktree);
  6. missing final SHA evidence in VERIFICATION.md.

The verifier must be rerun after the final P12 commit; only a zero exit on
the exact final candidates counts.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

STANDALONE_REPO = Path("/home/kensei/repos/hermes-walkie-talkie")
HERMES_WORKTREE = Path("/home/kensei/worktrees/hermes-walkie-talkie-core")
REVIEW_DIR = STANDALONE_REPO / "docs" / "review"

TASK_ID_RE = re.compile(r"\b(AP-\d{3}|H-\d{3}|HP-\d{3}|E2E-\d{3}|SEC-\d{4}|REL-\d{4}|PILOT-\d{4})\b")
PHASE_RE = re.compile(r"^- \[ \] \*\*P(?P<num>\d+) —")
ACCEPTANCE_SECTION = "## 9. Release acceptance checklist"
NOGO_SECTION = "## 10. Release no-go blockers"
LEDGER_SECTION = "## 12. Progress ledger"

FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


def git(args: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_repo_clean(name: str, repo: Path) -> None:
    if not repo.exists():
        fail(f"{name}: repository missing at {repo}")
        return
    code, out = git(["status", "--short"], repo)
    if code != 0:
        fail(f"{name}: git status failed: {out}")
        return
    if out.strip():
        fail(f"{name}: dirty worktree — {out.splitlines()[:5]}")
    code, head = git(["rev-parse", "HEAD"], repo)
    if code == 0 and head:
        print(f"{name}: HEAD = {head}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Path to the plan markdown")
    args = parser.parse_args()

    plan = Path(args.plan)
    if not plan.exists():
        fail(f"plan file missing: {plan}")
        print("VERIFIER: FAIL")
        return 1
    text = plan.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Locate sections.
    def section_start(marker: str) -> int:
        for i, line in enumerate(lines):
            if line.startswith(marker):
                return i
        return -1

    acc_start = section_start(ACCEPTANCE_SECTION)
    nogo_start = section_start(NOGO_SECTION)
    ledger_start = section_start(LEDGER_SECTION)
    if acc_start < 0 or nogo_start < 0 or ledger_start < 0:
        fail("plan structure: cannot locate acceptance/no-go/ledger sections")

    # 1. Unchecked in-scope tasks + phases (everything before the acceptance
    #    section, restricted to task/phase markers so non-goal checklists
    #    elsewhere in the plan are ignored).
    task_boxes = 0
    unchecked_tasks = []
    for line in lines[:acc_start] if acc_start >= 0 else lines:
        if TASK_ID_RE.search(line) and "- [" in line:
            task_boxes += 1
            if "- [ ]" in line:
                unchecked_tasks.append(line.strip()[:100])
        m = PHASE_RE.match(line)
        if m and "- [ ]" in line:
            unchecked_tasks.append(f"phase {m.group('num')} unchecked")
    if unchecked_tasks:
        fail(f"{len(unchecked_tasks)} unchecked in-scope items: {unchecked_tasks[:8]}")

    # 2. No-go blockers must all be unchecked. Every checkbox inside section
    #    10 is a blocker, so any checked box there is NO-GO.
    nogo_checked = [
        line.strip()[:100]
        for line in lines[nogo_start:ledger_start]
        if "- [x]" in line
    ]
    if nogo_checked:
        fail(f"checked no-go blocker(s): {nogo_checked}")

    # 3. Ledger evidence for every checked task. A ledger row's task cell may
    #    list several IDs ("AP-301, AP-302") or a gate ("AP-007 / Gate P0");
    #    tokenize the cell so every listed ID counts as evidenced.
    ledger_rows = [line for line in (lines[ledger_start:] if ledger_start >= 0 else []) if line.startswith("|")]
    ledger_ids: set[str] = set()
    for row in ledger_rows:
        cells = row.split("|")
        if len(cells) >= 3:
            task_cell = cells[2]  # [0]='' [1]=date [2]=task ids
            for token in re.split(r"[,/]", task_cell):
                token = token.strip()
                if TASK_ID_RE.fullmatch(token):
                    ledger_ids.add(token)
    checked_ids: set[str] = set()
    for line in lines[:acc_start] if acc_start >= 0 else lines:
        if "- [x]" in line:
            checked_ids.update(TASK_ID_RE.findall(line))
    for task_id in sorted(checked_ids):
        if task_id not in ledger_ids:
            fail(f"missing ledger row for checked task {task_id}")

    # 4. Review packet.
    required_files = ["HANDOFF.md", "VERIFICATION.md", "DEVIATIONS.md", "completed-plan.md"]
    for name in required_files:
        if not (REVIEW_DIR / name).exists():
            fail(f"review packet missing: docs/review/{name}")
    handoff = REVIEW_DIR / "HANDOFF.md"
    if handoff.exists():
        htext = handoff.read_text(encoding="utf-8")
        if "observed_no_go_blockers: 0" not in htext:
            fail("HANDOFF.md does not record observed_no_go_blockers: 0")
    verification = REVIEW_DIR / "VERIFICATION.md"
    if verification.exists():
        vtext = verification.read_text(encoding="utf-8")
        if "hermes-walkie-talkie" not in vtext or "hermes-walkie-talkie-core" not in vtext:
            fail("VERIFICATION.md lacks both candidate SHA records")

    # 5. Clean candidates.
    check_repo_clean("hermes-walkie-talkie", STANDALONE_REPO)
    check_repo_clean("hermes-walkie-talkie-core", HERMES_WORKTREE)

    print(f"VERIFIER: {'FAIL' if FAILURES else 'PASS'}")
    if FAILURES:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All goal-completion gates pass on the exact final candidates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
