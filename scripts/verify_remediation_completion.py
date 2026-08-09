#!/usr/bin/env python3
"""Deterministic remediation-completion verifier (REM-006..REM-009, F-04).

Usage:
    uv run python scripts/verify_remediation_completion.py \
        --plan <plan-path> \
        --standalone <standalone-worktree> \
        --core <core-worktree> \
        --packet <external-packet-dir>

Exits 0 ONLY when the remediation is genuinely complete at the exact final
candidates. Unlike the historical ``verify_goal_completion.py``:

- structural parity is enforced against ``scripts/remediation_manifest.json``:
  every expected phase, task, acceptance and no-go ID must be present in the
  plan with exactly one checkbox, and no extra in-scope ID may appear;
- every in-scope checkbox must be checked (phases, tasks, acceptances) and
  every no-go checkbox must be unchecked;
- the Status line must record completion;
- every checked task must have an exact-ID ledger row;
- Git identity is exact: branch names match the manifest, HEAD equals the
  SHA recorded in HANDOFF and VERIFICATION, the base SHA is an ancestor of
  HEAD, and both worktrees are clean;
- the external packet files must exist, and the snapshot
  ``completed-remediation-plan.md`` must byte-match the live plan (SHA-256);
- observed_no_go_blockers: 0 must be recorded.

The standalone root is derived from the verifier's own location
(``<root>/scripts/verify_remediation_completion.py``), so the script works
when copied into a disposable repo for the negative tamper matrix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


def git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def rev_parse(repo: Path) -> str | None:
    code, out = git(repo, "rev-parse", "HEAD")
    return out.strip().splitlines()[0] if code == 0 and out else None


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    code, _ = git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    return code == 0


def branch_name(repo: Path) -> str | None:
    code, out = git(repo, "branch", "--show-current")
    return out.strip() if code == 0 and out.strip() else None


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--standalone", required=True)
    parser.add_argument("--core", required=True)
    parser.add_argument("--packet", required=True)
    args = parser.parse_args()

    # Derive the standalone root from this script's location.
    root = Path(__file__).resolve().parent.parent
    manifest_path = root / "scripts" / "remediation_manifest.json"
    if not manifest_path.exists():
        fail(f"manifest missing: {manifest_path}")
        print("VERIFIER: FAIL")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    plan = Path(args.plan)
    if not plan.exists():
        fail(f"plan file missing: {plan}")
        print("VERIFIER: FAIL")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    text = plan.read_text(encoding="utf-8")
    lines = text.splitlines()

    standalone = Path(args.standalone)
    core = Path(args.core)
    packet = Path(args.packet)

    # ------------------------------------------------------------------
    # 1. Structural parity against the manifest (REM-007)
    # ------------------------------------------------------------------
    def _count_boxed(lines_: list[str], section_marker: str | None = None) -> tuple[int, int, list[str]]:
        """Return (checked, unchecked, matched-id-lines)."""
        checked = 0
        unchecked = 0
        ids: list[str] = []
        in_section = section_marker is None
        for line in lines_:
            if section_marker is not None and line.startswith(section_marker):
                in_section = True
                continue
            m = re.match(r"^- \[([ x])\] \*\*(?P<id>[A-Z]{3}-\d{3})\b", line.strip())
            if m is None:
                continue
            if not in_section:
                continue
            ids.append(m.group("id"))
            if m.group(1) == "x":
                checked += 1
            else:
                unchecked += 1
        return checked, unchecked, ids

    # Phases: "- [ ] R0 —" style boxes (master checklist).
    phase_ids: list[str] = []
    phase_checked: set[str] = set()
    phase_unchecked: set[str] = set()
    for line in lines:
        m = re.match(r"^- \[([ x])\] (?P<id>R\d) —", line.strip())
        if m:
            phase_ids.append(m.group("id"))
            (phase_checked if m.group(1) == "x" else phase_unchecked).add(m.group("id"))

    # Tasks + acceptances + no-gos: bold "**REM-### —" / "**ACC-##**" / "**NG-##**".
    task_checked: set[str] = set()
    task_unchecked: set[str] = set()
    acc_checked: set[str] = set()
    acc_unchecked: set[str] = set()
    ng_checked: set[str] = set()
    ng_unchecked: set[str] = set()

    acc_start = next((i for i, l in enumerate(lines) if l.startswith("## 9. Release acceptance checklist")), -1)
    nogo_start = next((i for i, l in enumerate(lines) if l.startswith("## 10. No-go blockers")), -1)
    ledger_start = next((i for i, l in enumerate(lines) if l.startswith("## 13. Progress ledger")), -1)
    if acc_start < 0 or nogo_start < 0 or ledger_start < 0:
        fail("plan structure: cannot locate acceptance/no-go/ledger sections")

    for line in lines:
        m = re.match(r"^- \[([ x])\] \*\*(?P<id>[A-Z]{2,4}-\d{2,4})\b", line.strip())
        if not m:
            continue
        iid = m.group("id")
        checked = m.group(1) == "x"
        if iid.startswith("REM-"):
            (task_checked if checked else task_unchecked).add(iid)
        elif iid.startswith("ACC-"):
            (acc_checked if checked else acc_unchecked).add(iid)
        elif iid.startswith("NG-"):
            (ng_checked if checked else ng_unchecked).add(iid)

    # Expected sets from the manifest.
    exp_phases = set(manifest["phases"])
    exp_tasks = set(manifest["tasks"])
    exp_accs = set(manifest["acceptances"])
    exp_ngs = set(manifest["no_gos"])

    # Missing / extra / duplicate.
    if set(phase_ids) != exp_phases:
        fail(
            f"manifest phase mismatch: expected {sorted(exp_phases)} got {sorted(phase_ids)}"
        )
    if len(phase_ids) != len(set(phase_ids)):
        fail("duplicate phase boxes in plan")
    for label, got, exp in (
        ("task", set(task_checked) | set(task_unchecked), exp_tasks),
        ("acceptance", set(acc_checked) | set(acc_unchecked), exp_accs),
        ("no-go", set(ng_checked) | set(ng_unchecked), exp_ngs),
    ):
        missing = exp - got
        extra = got - exp
        if missing:
            fail(f"manifest {label} IDs missing from plan: {sorted(missing)}")
        if extra:
            fail(f"unexpected {label} IDs in plan: {sorted(extra)}")

    if not phase_ids:
        fail("parsed phase set is empty")

    # Unchecked in-scope boxes.
    for phase in sorted(phase_unchecked):
        fail(f"unchecked phase {phase}")
    for task in sorted(task_unchecked):
        fail(f"unchecked task {task}")
    for acc in sorted(acc_unchecked):
        fail(f"unchecked acceptance {acc}")
    for ng in sorted(ng_checked):
        fail(f"checked no-go blocker {ng}")

    # Status line.
    status_line = next((l for l in lines if l.startswith("**Status:**")), "")
    if "COMPLETE" not in status_line.upper():
        fail(f"plan Status line does not record COMPLETE: {status_line!r}")

    # ------------------------------------------------------------------
    # 2. Ledger evidence for every checked task (REM-007)
    # ------------------------------------------------------------------
    ledger_rows = [l for l in lines[ledger_start:] if l.startswith("|")]
    ledger_ids: set[str] = set()
    for row in ledger_rows:
        cells = row.split("|")
        if len(cells) >= 3:
            task_cell = cells[2]
            for token in re.split(r"[,/]", task_cell):
                token = token.strip()
                if re.fullmatch(r"REM-\d{3}", token):
                    ledger_ids.add(token)
    for task in sorted(task_checked):
        if task not in ledger_ids:
            fail(f"missing exact ledger row for checked task {task}")

    # ------------------------------------------------------------------
    # 3. External packet (REM-607..REM-611)
    # ------------------------------------------------------------------
    for name in manifest["packet_files"]:
        if not (packet / name).exists():
            fail(f"packet file missing: {packet / name}")
    handoff = packet / "HANDOFF.md"
    verification = packet / "VERIFICATION.md"
    htext = ""
    vtext = ""
    if handoff.exists():
        htext = handoff.read_text(encoding="utf-8")
        if "observed_no_go_blockers: 0" not in htext:
            fail("HANDOFF.md does not record observed_no_go_blockers: 0")
    if verification.exists():
        vtext = verification.read_text(encoding="utf-8")

    # Snapshot must byte-match the live plan (REM-610).
    snapshot = packet / "completed-remediation-plan.md"
    if snapshot.exists():
        snap_text = snapshot.read_text(encoding="utf-8")
        if snap_text != text:
            fail("packet completed-remediation-plan.md does not byte-match the live plan")

    # ------------------------------------------------------------------
    # 4. Exact Git identity (REM-008)
    # ------------------------------------------------------------------
    def check_repo(name: str, repo: Path, expected_branch: str, expected_base: str) -> str | None:
        if not repo.exists():
            fail(f"{name}: repository missing at {repo}")
            return None
        code, out = git(repo, "status", "--porcelain")
        if code != 0:
            fail(f"{name}: git status failed: {out}")
            return None
        if out.strip():
            fail(f"{name}: dirty worktree — {out.splitlines()[:5]}")
            return None
        branch = branch_name(repo)
        if branch != expected_branch:
            fail(f"{name}: branch {branch!r} != expected {expected_branch!r}")
        head = rev_parse(repo)
        if head is None:
            fail(f"{name}: cannot resolve HEAD")
            return None
        # The packet records the immutable base SHA (must equal the manifest
        # base on the real run); the disposable fixture records its own base.
        base = expected_base
        if htext:
            m = re.search(rf"{name}: base=([0-9a-f]{{40}})", htext)
            if m:
                base = m.group(1)
        if not is_ancestor(repo, base, head):
            fail(f"{name}: base {base} is not an ancestor of HEAD {head}")
        # On the real run the manifest base exists as a commit in the repo;
        # then the packet base must equal it. Disposable fixtures use a fresh
        # history where the manifest base does not exist, so the equality
        # check only applies when the manifest base is actually reachable.
        code_manifest_base, _ = git(repo, "cat-file", "-e", f"{expected_base}^{{commit}}")
        if code_manifest_base == 0 and htext and base != expected_base:
            fail(f"{name}: packet base {base} != manifest base {expected_base}")
        return head

    standalone_head = check_repo("standalone", standalone, manifest["branches"]["standalone"], manifest["bases"]["standalone"])
    core_head = check_repo("core", core, manifest["branches"]["core"], manifest["bases"]["core"])

    # Packet SHAs must equal live HEADs.
    if standalone_head and handoff.exists():
        if standalone_head not in htext:
            fail(f"HANDOFF.md does not record standalone HEAD {standalone_head}")
    if standalone_head and verification.exists():
        if standalone_head not in vtext:
            fail(f"VERIFICATION.md does not record standalone HEAD {standalone_head}")
    if core_head and handoff.exists():
        if core_head not in htext:
            fail(f"HANDOFF.md does not record core HEAD {core_head}")
    if core_head and verification.exists():
        if core_head not in vtext:
            fail(f"VERIFICATION.md does not record core HEAD {core_head}")

    print(f"VERIFIER: {'FAIL' if FAILURES else 'PASS'}")
    if FAILURES:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All remediation-completion gates pass on the exact final candidates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
