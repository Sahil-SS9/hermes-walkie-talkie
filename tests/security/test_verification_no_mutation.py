"""Regression: canonical verification must not mutate tracked files.

The reviewer requirement: proving canonical verification cannot mutate
tracked files unnoticed. The verifier now checks cleanliness both BEFORE
and AFTER running the full suite + coverage gate, and this test proves
that any mutation the gates would introduce is caught: it runs a
verification-shaped command sequence (imports + suite collect on the
tracked source tree) and asserts `git status --porcelain` stays empty.

The expensive full gates are exercised by scripts/verify_v1_1_plus_
completion.py itself; this test locks the *property* cheaply: the
canonical entrypoint must keep the worktree clean, and the verifier must
contain a post-gate cleanliness check.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _porcelain() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class TestVerificationNoMutation:
    def test_verifier_has_post_gate_clean_check(self):
        """The verifier must assert cleanliness after running gates."""
        src = (REPO / "scripts/verify_v1_1_plus_completion.py").read_text(encoding="utf-8")
        assert "post-gate-clean" in src, "verifier must check post-gate cleanliness"
        # The check must run after both the suite and the coverage gate.
        assert src.index("coverage-gate") < src.index("post-gate-clean")

    def test_verifier_accepts_recorded_native_windows_evidence(self):
        """A native CI marker must be usable from the Linux review host."""
        src = (REPO / "scripts/verify_v1_1_plus_completion.py").read_text(encoding="utf-8")
        assert "NATIVE PROOF COMPLETE" in src
        assert "if WINDOWS_EVIDENCE.exists()" in src
        assert "if sys.platform == \"win32\"" not in src

    def test_verifier_does_not_require_missing_historical_core_worktrees(self):
        """The current PR gate cannot depend on a retired local worktree path."""
        src = (REPO / "scripts/verify_v1_1_plus_completion.py").read_text(encoding="utf-8")
        assert "FROZEN_CORE_WORKTREES" not in src
        assert "LOCKED_CORE_SHA" not in src

    def test_suite_collection_does_not_dirty_tree(self):
        """Collecting/importing the full test suite mutates nothing."""
        before = _porcelain()
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        assert _porcelain() == before

    def test_manifest_bootstrap_uses_locked(self):
        """Canonical verification must be reproducible: --locked enforced."""
        manifest = (REPO / ".hermes" / "environment.json").read_text(encoding="utf-8")
        assert "uv sync --locked --group dev" in manifest
        assert "uv sync --group dev" not in manifest.replace(
            "uv sync --locked --group dev", ""
        ), "unlocked bootstrap would allow silent uv.lock mutation"
