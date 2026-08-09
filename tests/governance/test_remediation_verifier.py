"""RED tests for the corrected remediation completion verifier (REM-005..REM-009).

The historical verifier (``scripts/verify_goal_completion.py``) silently
ignored the plan's phase boxes (its ``PHASE_RE`` matched literal ``**P``
markdown that the plan never used), compared SHAs only by substring, and
hardcoded the old standalone repository path. These tests pin the
replacement contract:

- manifest-backed structural parity (phases, tasks, acceptances, no-gos);
- exact Git identity (base ancestry, branch, clean status, final SHA);
- exact external packet files and snapshot hash agreement;
- a negative tamper matrix where every single mutation fails for its
  intended reason.

The tests build disposable copies: a temp Git repo (with the verifier and
manifest copied in, since the verifier derives its standalone root from its
own location), a fake but complete plan, and a fake packet. A helper makes a
fully-passing baseline, then each negative case mutates exactly one thing.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
MANIFEST = SCRIPTS / "remediation_manifest.json"
VERIFIER = SCRIPTS / "verify_remediation_completion.py"

STANDALONE_BASE = "1722a7cfa910befc4e6992767c44c66857a7e57a"
CORE_BASE = "5e7a111b3e748b0cfeb463f536ca52ad0db468fd"
STANDALONE_BRANCH = "candidate/hwt-remediation-20260809"
CORE_BRANCH = "candidate/hwt-core-remediation-20260809"

# The historical PHASE_RE defect: it demanded literal bold "**P<n> —".
OLD_PHASE_RE = re.compile(r"^- \[ \] \*\*P(?P<num>\d+) —")


def _make_plan(status: str = "COMPLETE", *, check: dict[str, bool] | None = None) -> str:
    """Build a complete fake plan. ``check`` overrides specific boxes."""
    check = check or {}
    lines: list[str] = []
    lines.append(f"# Fake Remediation Plan")
    lines.append("")
    lines.append(f"**Status:** {status}")
    lines.append("")
    lines.append("## 6. Master phase checklist")
    lines.append("")
    for phase in [f"R{i}" for i in range(7)]:
        checked = check.get(f"phase:{phase}", True)
        box = "[x]" if checked else "[ ]"
        lines.append(f"- {box} {phase} — Fake phase {phase}")
    lines.append("")
    lines.append("## 7. Detailed remediation checklist")
    lines.append("")
    for task in _manifest_tasks():
        checked = check.get(f"task:{task}", True)
        box = "[x]" if checked else "[ ]"
        lines.append(f"- {box} **{task} — Fake task.** Body.")
    lines.append("")
    lines.append("## 9. Release acceptance checklist")
    lines.append("")
    for acc in _manifest_accs():
        checked = check.get(f"acc:{acc}", True)
        box = "[x]" if checked else "[ ]"
        lines.append(f"- {box} **{acc}** Fake acceptance.")
    lines.append("")
    lines.append("## 10. No-go blockers")
    lines.append("")
    for ng in _manifest_ngs():
        checked = check.get(f"ng:{ng}", False)
        box = "[x]" if checked else "[ ]"
        lines.append(f"- {box} **{ng}** Fake no-go.")
    lines.append("")
    lines.append("## 13. Progress ledger")
    lines.append("")
    lines.append("| Date | Task | Status | Repository/commit | RED evidence | GREEN/regression evidence | Notes |")
    lines.append("|---|---|---|---|---|---|---|")
    for task in _manifest_tasks():
        lines.append(f"| 09/08/2026 | {task} | Complete | fake@deadbeef | red | green | test |")
    lines.append("")
    return "\n".join(lines)


def _manifest_tasks() -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data["tasks"]


def _manifest_accs() -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data["acceptances"]


def _manifest_ngs() -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data["no_gos"]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def disposable(tmp_path: Path):
    """A self-contained disposable copy: repo + verifier + manifest + plan + packet."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Copy the verifier and manifest so the verifier's derived root == repo.
    shutil.copytree(SCRIPTS, repo / "scripts", dirs_exist_ok=True)

    _git(repo, "init", "-b", STANDALONE_BRANCH)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")

    # Base commit.
    _write(repo / "README.md", "base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert base == STANDALONE_BASE or True  # disposable base is not the real SHA

    # Final commit carrying the verifier + manifest + plan + packet.
    plan_text = _make_plan()
    plan_path = tmp_path / "plan.md"
    _write(plan_path, plan_text)
    plan_hash = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()

    packet = tmp_path / "packet"
    packet.mkdir()
    _write(packet / "HANDOFF.md", _handoff(plan_hash))
    _write(packet / "VERIFICATION.md", _verification(plan_hash))
    _write(packet / "DEVIATIONS.md", "# Deviations\n\nNone.\n")
    _write(packet / "completed-remediation-plan.md", plan_text)

    # Commit everything so status is clean and HEAD is a descendant of base.
    _write(repo / "scripts" / "verify_remediation_completion.py", VERIFIER.read_text(encoding="utf-8"))
    _write(repo / "scripts" / "remediation_manifest.json", MANIFEST.read_text(encoding="utf-8"))
    _write(repo / "plan.md", plan_text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "final")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # A disposable core worktree-like repo.
    core = tmp_path / "core"
    core.mkdir()
    _git(core, "init", "-b", CORE_BRANCH)
    _git(core, "config", "user.email", "t@t")
    _git(core, "config", "user.name", "T")
    _write(core / "core.txt", "core\n")
    _git(core, "add", "-A")
    _git(core, "commit", "-m", "core-base")
    _git(core, "commit", "--allow-empty", "-m", "core-final")
    core_head = _git(core, "rev-parse", "HEAD").stdout.strip()
    core_base = _git(core, "rev-parse", "HEAD~1").stdout.strip()

    # The packet must reference the disposable HEADs, not the real bases.
    handoff = _handoff(plan_hash, standalone=head, core=core_head, standalone_base=base, core_base=core_base)
    verification = _verification(plan_hash, standalone=head, core=core_head)
    _write(packet / "HANDOFF.md", handoff)
    _write(packet / "VERIFICATION.md", verification)

    from types import SimpleNamespace

    return SimpleNamespace(
        repo=repo,
        core=core,
        plan=plan_path,
        packet=packet,
        plan_hash=plan_hash,
        standalone_head=head,
        core_head=core_head,
        core_base=core_base,
        standalone_base=base,
    )


def _handoff(
    plan_hash: str,
    *,
    standalone: str = "0" * 40,
    core: str = "0" * 40,
    standalone_base: str = "0" * 40,
    core_base: str = "0" * 40,
) -> str:
    return (
        "# Handoff\n\n"
        "| Repository | Branch | Commit | Clean |\n"
        "|---|---|---|---|\n"
        f"| hermes-walkie-talkie | {STANDALONE_BRANCH} | {standalone} | yes |\n"
        f"| hermes-walkie-talkie-core | {CORE_BRANCH} | {core} | yes |\n\n"
        f"standalone: base={standalone_base}\n"
        f"core: base={core_base}\n\n"
        "observed_no_go_blockers: 0\n\n"
        f"completed-remediation-plan.md SHA-256: {plan_hash}\n"
    )


def _verification(plan_hash: str, *, standalone: str = "0" * 40, core: str = "0" * 40) -> str:
    return (
        "# Verification\n\n"
        f"- hermes-walkie-talkie: {standalone}\n"
        f"- hermes-walkie-talkie-core: {core}\n\n"
        "All gates passed.\n\n"
        f"completed-remediation-plan.md SHA-256: {plan_hash}\n"
    )


def run_verifier(d) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(d.repo / "scripts" / "verify_remediation_completion.py"),
            "--plan", str(d.plan),
            "--standalone", str(d.repo),
            "--core", str(d.core),
            "--packet", str(d.packet),
        ],
        capture_output=True, text=True, timeout=120,
    )


# ---------------------------------------------------------------------------
# RED: the old verifier approach cannot express the required contract
# ---------------------------------------------------------------------------


class TestOldVerifierDefect:
    def test_old_phase_regex_never_matches_the_plan_format(self):
        """The historical PHASE_RE required literal '**P<n> —'; the plan uses
        '- [ ] R0 —'. Prove the regex cannot match the real format, which is
        why the old verifier silently ignored every phase gate."""
        line = "- [ ] R0 — Fresh lanes and trustworthy completion evidence"
        assert OLD_PHASE_RE.match(line) is None
        # And it would not match the remediation format either.
        assert OLD_PHASE_RE.match("- [x] R1 — Done") is None

    def test_old_substring_sha_check_is_not_exact(self):
        """The old verifier checked only that the strings
        'hermes-walkie-talkie' / 'hermes-walkie-talkie-core' appeared in
        VERIFICATION.md — never comparing against `git rev-parse HEAD`."""
        vtext = "hermes-walkie-talkie: 0000...\nhermes-walkie-talkie-core: 0000...\n"
        assert "hermes-walkie-talkie" in vtext
        assert "hermes-walkie-talkie-core" in vtext
        # A substring check would pass here even though no real SHA is present.
        assert re.search(r"\b[0-9a-f]{40}\b", vtext) is None


class TestVerifierContract:
    """The new verifier must exist and satisfy the manifest contract."""

    def test_verifier_script_exists(self):
        assert VERIFIER.exists(), "verify_remediation_completion.py must exist"

    def test_manifest_exists_and_is_complete(self):
        assert MANIFEST.exists()
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert data["phases"] == ["R0", "R1", "R2", "R3", "R4", "R5", "R6"]
        assert len(data["tasks"]) == 10 + 14 + 14 + 12 + 12 + 13 + 14  # 89
        assert len(data["acceptances"]) == 18
        assert len(data["no_gos"]) == 15
        assert data["bases"]["standalone"] == STANDALONE_BASE
        assert data["bases"]["core"] == CORE_BASE
        # No duplicates.
        for key in ("tasks", "acceptances", "no_gos"):
            ids = data[key]
            assert len(ids) == len(set(ids)), f"duplicate {key}"

    def test_baseline_passes(self, disposable):
        proc = run_verifier(disposable)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    # -- negative tamper matrix (REM-009) -----------------------------------

    def test_unchecked_phase_fails(self, disposable):
        _write(disposable.plan, _make_plan(check={"phase:R2": False}))
        _write(disposable.packet / "completed-remediation-plan.md", _make_plan(check={"phase:R2": False}))
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "unchecked phase R2" in proc.stdout + proc.stderr

    def test_unchecked_task_fails(self, disposable):
        _write(disposable.plan, _make_plan(check={"task:REM-301": False}))
        _write(disposable.packet / "completed-remediation-plan.md", _make_plan(check={"task:REM-301": False}))
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "unchecked task REM-301" in proc.stdout + proc.stderr

    def test_unchecked_acceptance_fails(self, disposable):
        _write(disposable.plan, _make_plan(check={"acc:ACC-09": False}))
        _write(disposable.packet / "completed-remediation-plan.md", _make_plan(check={"acc:ACC-09": False}))
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "unchecked acceptance ACC-09" in proc.stdout + proc.stderr

    def test_status_not_complete_fails(self, disposable):
        _write(disposable.plan, _make_plan(status="IN PROGRESS — R0"))
        _write(disposable.packet / "completed-remediation-plan.md", _make_plan(status="IN PROGRESS — R0"))
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "status" in (proc.stdout + proc.stderr).lower()

    def test_missing_ledger_row_fails(self, disposable):
        text = _make_plan()
        text = text.replace("| 09/08/2026 | REM-101 |", "| 09/08/2026 | REM-101,REM-102 |")
        # Remove REM-101 from its row entirely: replace the row with only REM-102.
        lines = text.splitlines()
        out = []
        for line in lines:
            if "REM-101" in line and line.startswith("|") and "REM-101,REM-102" in line:
                line = line.replace("REM-101,REM-102", "REM-102")
            out.append(line)
        text = "\n".join(out)
        _write(disposable.plan, text)
        _write(disposable.packet / "completed-remediation-plan.md", text)
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "ledger" in (proc.stdout + proc.stderr).lower()

    def test_standalone_sha_mismatch_fails(self, disposable):
        # HEAD moved after the packet was written (simulate by making a new
        # commit without updating the packet).
        _write(disposable.repo / "extra.txt", "x\n")
        _git(disposable.repo, "add", "extra.txt")
        _git(disposable.repo, "commit", "-m", "drift")
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "standalone" in (proc.stdout + proc.stderr).lower() and "head" in (proc.stdout + proc.stderr).lower()

    def test_core_sha_mismatch_fails(self, disposable):
        _write(disposable.core / "extra.txt", "x\n")
        _git(disposable.core, "add", "extra.txt")
        _git(disposable.core, "commit", "-m", "drift")
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "core" in (proc.stdout + proc.stderr).lower() and "head" in (proc.stdout + proc.stderr).lower()

    def test_standalone_dirty_fails(self, disposable):
        _write(disposable.repo / "untracked.txt", "x\n")
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "dirty" in (proc.stdout + proc.stderr).lower()

    def test_core_dirty_fails(self, disposable):
        _write(disposable.core / "untracked.txt", "x\n")
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "dirty" in (proc.stdout + proc.stderr).lower()

    def test_plan_snapshot_mismatch_fails(self, disposable):
        # Packet snapshot differs from the live plan.
        _write(disposable.packet / "completed-remediation-plan.md", _make_plan() + "\ntampered\n")
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "snapshot" in (proc.stdout + proc.stderr).lower() or "byte-match" in (proc.stdout + proc.stderr).lower()

    def test_checked_no_go_fails(self, disposable):
        _write(disposable.plan, _make_plan(check={"ng:NG-04": True}))
        _write(disposable.packet / "completed-remediation-plan.md", _make_plan(check={"ng:NG-04": True}))
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "no-go" in (proc.stdout + proc.stderr).lower()

    def test_empty_parsed_set_fails(self, disposable):
        # A plan with zero phase boxes must fail the structural-parity gate.
        text = _make_plan()
        text = re.sub(r"^- \[[ x]\] R\d —.*$", "", text, flags=re.M)
        _write(disposable.plan, text)
        _write(disposable.packet / "completed-remediation-plan.md", text)
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "phase" in (proc.stdout + proc.stderr).lower()

    def test_missing_packet_file_fails(self, disposable):
        (disposable.packet / "DEVIATIONS.md").unlink()
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "packet" in (proc.stdout + proc.stderr).lower()

    def test_wrong_branch_fails(self, disposable):
        _git(disposable.repo, "branch", "-m", "wrong/branch")
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "branch" in (proc.stdout + proc.stderr).lower()

    def test_base_not_ancestor_fails(self, disposable):
        # Rewrite history so the base is not an ancestor of HEAD.
        _git(disposable.repo, "checkout", "--orphan", "orphan")
        _git(disposable.repo, "rm", "-rf", ".")
        _write(disposable.repo / "fresh.txt", "fresh\n")
        _git(disposable.repo, "add", "-A")
        _git(disposable.repo, "commit", "-m", "orphan")
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "ancestor" in (proc.stdout + proc.stderr).lower()

    def test_missing_manifest_id_fails(self, disposable):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        data["tasks"] = [t for t in data["tasks"] if t != "REM-001"]
        _write(disposable.repo / "remediation_manifest.json", json.dumps(data))
        proc = run_verifier(disposable)
        assert proc.returncode != 0
        assert "manifest" in (proc.stdout + proc.stderr).lower()
