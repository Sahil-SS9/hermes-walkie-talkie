"""Platform path backend selection tests (P1.5, G5.5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_peer.platform_paths import get_path_backend


def test_auto_selects_posix_on_linux():
    if sys.platform == "win32":
        pytest.skip("not a POSIX platform")
    backend = get_path_backend()
    assert backend.kind == "posix"


def test_explicit_posix():
    backend = get_path_backend(platform="posix")
    assert backend.kind == "posix"


def test_explicit_windows_selects_windows_backend():
    backend = get_path_backend(platform="win32")
    assert backend.kind == "windows"


def test_windows_backend_fails_closed_before_native_proof():
    backend = get_path_backend(platform="win32")
    with pytest.raises(NotImplementedError):
        backend.select_runtime_dir()
    with pytest.raises(NotImplementedError):
        backend.select_state_dir()
    with pytest.raises(NotImplementedError):
        backend.validate_runtime_dir(Path("/tmp/x"))
    with pytest.raises(NotImplementedError):
        backend.socket_path_for(Path("/tmp"), "peer", "instance")
