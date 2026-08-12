"""Shared test fixtures and helpers for Hermes Walkie Talkie."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Short-path tmp dir for AF_UNIX socket tests.

    pytest's default tmp_path nests under the runner's deep temp dir
    (e.g. /home/runner/work/<repo>/<repo>/pytest-of-runner/...), which
    exceeds the ~108-byte AF_UNIX sun_path limit on CI runners.
    A short /tmp prefix keeps socket paths well under the limit while
    preserving per-test isolation.
    """
    with tempfile.TemporaryDirectory(prefix="aps-") as d:
        # resolve() so macOS /var/folders -> /private/var symlink does not
        # diverge from os.getcwd()/realpath inside host_metadata().
        yield Path(d).resolve()


@pytest.fixture
def isolated_runtime(monkeypatch):
    """Point runtime/state roots at a fresh temporary owner-local directory.

    Every test gets its own runtime root so tests never see real peers or
    each other's state.
    """
    with tempfile.TemporaryDirectory(prefix="agent-peer-test-") as tmp:
        runtime = Path(tmp) / "runtime"
        state = Path(tmp) / "state"
        runtime.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(Path(tmp) / "xdg-runtime"))
        monkeypatch.setenv("XDG_STATE_HOME", str(state))
        monkeypatch.delenv("AGENT_PEER_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("AGENT_PEER_STATE_DIR", raising=False)
        yield runtime, state


@pytest.fixture
def fresh_state_dir(isolated_runtime):
    """Convenience alias returning just the state directory."""
    _, state = isolated_runtime
    return state


_CORE_ROOT = Path(os.environ.get("HERMES_CORE_ROOT", "/home/kensei/worktrees/hermes-walkie-talkie-core-remediation-r2"))


@pytest.fixture
def require_hermes_core():
    """Skip real-Hermes-process tests when the core checkout is unavailable.

    These e2e tests spawn a genuine Hermes core (the peer plugin's runtime
    dependency) and are only meaningful where HERMES_CORE_ROOT exists — the
    dev box or a CI job that provisions the checkout. On runners without it,
    skip cleanly instead of failing on a hardcoded path.
    """
    if not _CORE_ROOT.exists():
        pytest.skip(f"HERMES_CORE_ROOT missing: {_CORE_ROOT}")
