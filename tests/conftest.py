"""Shared test fixtures and helpers for Hermes Walkie Talkie."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Short-path tmp dir for AF_UNIX socket tests.

    pytest's default tmp_path nests under the runner's deep temp dir
    (e.g. /home/runner/work/<repo>/<repo>/pytest-of-runner/pytest-0/test_x0/),
    which exceeds the ~108-byte AF_UNIX sun_path limit on CI runners —
    "OSError: AF_UNIX path too long". A short /tmp prefix keeps socket
    paths well under the limit while preserving per-test isolation.
    """
    with tempfile.TemporaryDirectory(prefix="aps-") as d:
        yield Path(d)


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
