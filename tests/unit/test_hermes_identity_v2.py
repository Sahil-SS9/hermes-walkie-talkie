"""Hermes session manager V2 identity tests (P3.1, G2.2/G2.3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_peer.sessions import PeerSessionManager, _hermes_home


class _Ctx:
    """Minimal host context: no hermes_home (bare test context)."""

    def __init__(self) -> None:
        self.injected: list[tuple] = []

    def inject_message(self, content, role="user", *, mode="queue", target_session=None):
        self.injected.append((content, role, mode, target_session))
        return True


class _HomeCtx(_Ctx):
    def __init__(self, home: Path) -> None:
        super().__init__()
        self.hermes_home = str(home)


@pytest.fixture()
def isolated_runtime(tmp_path):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    runtime.mkdir()
    state.mkdir()
    os.chmod(runtime, 0o700)
    os.chmod(state, 0o700)
    return runtime, state


def test_bare_context_never_writes_real_home(tmp_path, isolated_runtime, monkeypatch):
    """A context without hermes_home must NOT create ~/.hermes/agent-peer."""
    runtime_dir, _ = isolated_runtime
    monkeypatch.delenv("HERMES_HOME", raising=False)
    home = Path.home()
    marker = home / "agent-peer" / "agent_id"
    if marker.exists():
        marker.unlink()

    mgr = PeerSessionManager(_Ctx(), runtime_root=runtime_dir)
    try:
        mgr.on_session_open("sess-x", platform="cli")
        assert mgr._peers["sess-x"].agent_id  # ephemeral but valid
        assert not marker.exists()  # real profile untouched
    finally:
        mgr.shutdown()


def test_session_rotation_keeps_agent_id_changes_peer_id(tmp_path, isolated_runtime):
    """G2.2/P3.1: same adapter across reset -> same agent_id, new peer_id."""
    runtime_dir, _ = isolated_runtime
    home = tmp_path / "home"
    home.mkdir()
    ctx = _HomeCtx(home)

    mgr = PeerSessionManager(ctx, runtime_root=runtime_dir)
    try:
        mgr.on_session_open("s1", platform="cli")
        first_peer = mgr._peers["s1"].peer_id
        first_agent = mgr._peers["s1"].agent_id
        assert first_agent

        mgr.on_session_reset("s2", platform="cli", old_session_id="s1")

        assert mgr._peers["s2"].agent_id == first_agent
        assert mgr._peers["s2"].peer_id != first_peer
    finally:
        mgr.shutdown()


def test_agent_id_persists_across_manager_instances(tmp_path, isolated_runtime):
    """G2.3: agent_id survives process restart via the HERMES_HOME file."""
    runtime_dir, _ = isolated_runtime
    home = tmp_path / "home"
    home.mkdir()

    mgr1 = PeerSessionManager(_HomeCtx(home), runtime_root=runtime_dir)
    try:
        mgr1.on_session_open("s1", platform="cli")
        agent1 = mgr1._peers["s1"].agent_id
    finally:
        mgr1.shutdown()

    mgr2 = PeerSessionManager(_HomeCtx(home), runtime_root=runtime_dir)
    try:
        mgr2.on_session_open("s2", platform="cli")
        assert mgr2._peers["s2"].agent_id == agent1
    finally:
        mgr2.shutdown()


def test_v2_record_advertises_protocols_and_capabilities(tmp_path, isolated_runtime):
    runtime_dir, _ = isolated_runtime
    home = tmp_path / "home"
    home.mkdir()

    mgr = PeerSessionManager(_HomeCtx(home), runtime_root=runtime_dir)
    try:
        mgr.on_session_open("s1", platform="cli")
        rec = mgr._peers["s1"]
        assert "agent-peer/2" in rec.protocols
        assert isinstance(rec.capabilities, dict)
    finally:
        mgr.shutdown()


def test_hermes_home_prefers_ctx_over_env(tmp_path, monkeypatch):
    home = tmp_path / "ctx-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "env-home"))
    assert _hermes_home(_HomeCtx(home)) == home


def test_hermes_home_uses_env_when_ctx_bare(tmp_path, monkeypatch):
    env_home = tmp_path / "env-home"
    env_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(env_home))
    assert _hermes_home(_Ctx()) == env_home


def test_hermes_home_none_when_unknown(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert _hermes_home(_Ctx()) is None
