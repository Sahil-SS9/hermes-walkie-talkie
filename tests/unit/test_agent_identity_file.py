"""Agent identity persistence tests (P3.2, G2.3)."""

from __future__ import annotations

import os
import uuid

import pytest

from agent_peer.agent_identity import load_or_create_agent_id, read_agent_id
from agent_peer.errors import ConfigurationError


def test_creates_and_reloads_same_id(tmp_path):
    a = load_or_create_agent_id(tmp_path)
    b = load_or_create_agent_id(tmp_path)
    assert a == b
    assert uuid.UUID(a)  # valid UUID
    assert read_agent_id(tmp_path) == a


def test_id_is_owner_only(tmp_path):
    load_or_create_agent_id(tmp_path)
    path = tmp_path / "agent-peer" / "agent_id"
    st = path.stat()
    assert st.st_uid == os.geteuid()
    assert (st.st_mode & 0o077) == 0


def test_identity_dir_is_owner_only(tmp_path):
    load_or_create_agent_id(tmp_path)
    st = (tmp_path / "agent-peer").stat()
    assert (st.st_mode & 0o077) == 0


def test_read_absent_returns_empty(tmp_path):
    assert read_agent_id(tmp_path) == ""


def test_invalid_stored_id_is_refreshed(tmp_path):
    path = tmp_path / "agent-peer" / "agent_id"
    path.parent.mkdir(mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, b"not-a-uuid")
    finally:
        os.close(fd)
    a = load_or_create_agent_id(tmp_path)
    assert uuid.UUID(a)
    assert a != "not-a-uuid"


def test_world_readable_identity_refused(tmp_path):
    path = tmp_path / "agent-peer" / "agent_id"
    path.parent.mkdir(mode=0o700)
    path.write_text(str(uuid.uuid4()))
    os.chmod(path, 0o644)
    with pytest.raises(ConfigurationError):
        load_or_create_agent_id(tmp_path)


def test_symlinked_home_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ConfigurationError):
        load_or_create_agent_id(link)
