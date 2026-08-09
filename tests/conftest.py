"""Shared test fixtures and helpers for Hermes Walkie Talkie."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


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
