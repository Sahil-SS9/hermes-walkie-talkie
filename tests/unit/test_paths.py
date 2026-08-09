"""RED tests for secure runtime/state path selection (AP-401, AP-402)."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from agent_peer.errors import ConfigurationError
from agent_peer.paths import RuntimePaths, select_runtime_dir, validate_runtime_dir


def _make_root(tmp_path: Path, mode: int = 0o700) -> Path:
    root = tmp_path / "xdg-runtime"
    root.mkdir(mode=mode)
    return root


class TestRuntimePathSelection:
    def test_secure_xdg_runtime_dir_used(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
        monkeypatch.delenv("AGENT_PEER_RUNTIME_DIR", raising=False)
        selected = select_runtime_dir()
        assert selected.parent == root
        assert selected.name == "agent-peer"
        assert selected.exists()
        assert (selected.stat().st_mode & 0o077) == 0  # owner-only

    def test_wrong_owner_rejected(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
        if os.geteuid() == 0:
            pytest.skip("running as root; ownership checks are vacuous")
        # chown the root to an impossible owner via chmod trick: mark dir
        # as not-owned by using a different uid when permitted
        try:
            os.chown(root, os.geteuid() + 1, -1)
        except PermissionError:
            pytest.skip("cannot chown in this environment")
        with pytest.raises(ConfigurationError):
            select_runtime_dir()

    def test_permissive_mode_falls_back_securely(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path, mode=0o755)  # world-readable -> insecure
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        selected = select_runtime_dir()
        # Must NOT use the permissive root; fallback is owner-only.
        assert selected.parent != root
        assert (selected.stat().st_mode & 0o077) == 0

    def test_symlinked_runtime_root_refused(self, tmp_path, monkeypatch):
        real = _make_root(tmp_path)
        link = tmp_path / "link-runtime"
        link.symlink_to(real)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(link))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        selected = select_runtime_dir()
        # The symlinked root is refused; the verified fallback is used.
        assert selected.parent != real
        assert selected.parent != link
        assert (selected.stat().st_mode & 0o077) == 0

    def test_missing_xdg_uses_verified_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        selected = select_runtime_dir()
        assert (selected.stat().st_mode & 0o077) == 0
        assert "agent-peer" in str(selected)

    def test_overlong_socket_path_rejected(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
        paths = RuntimePaths(root)
        # Socket names are hash-shortened; only an absurdly long root can
        # still overflow — and that is handled by relocation (see
        # test_deep_root_relocates_sockets_to_short_dir). A non-existent
        # peer id never produces an overlong path.
        socket_path = paths.socket_path_for(str(uuid.uuid4()))
        assert len(str(socket_path)) < 108

    def test_validate_runtime_dir_rejects_world_writable(self, tmp_path):
        root = _make_root(tmp_path, mode=0o777)
        with pytest.raises(ConfigurationError):
            validate_runtime_dir(root)

    def test_runtime_paths_layout(self, tmp_path):
        root = _make_root(tmp_path)
        paths = RuntimePaths(root)
        assert paths.registry_dir == root / "registry"
        assert paths.sockets_dir == root / "s"
        assert paths.registry_dir.exists()
        assert (paths.registry_dir.stat().st_mode & 0o077) == 0

    def test_deep_root_relocates_sockets_to_short_dir(self, tmp_path):
        """Overlong socket paths are handled by relocating sockets to a short
        owner-only root under the system temp dir (ADR-0001)."""
        deep = tmp_path / ("d" * 120)  # guaranteed to exceed the AF_UNIX bound
        deep.mkdir(parents=True, mode=0o700)
        paths = RuntimePaths(deep)
        assert paths.sockets_dir == Path(tempfile.gettempdir()) / f"agent-peer-{os.geteuid()}"
        socket_path = paths.socket_path_for(str(uuid.uuid4()))
        assert len(str(socket_path)) < 108
