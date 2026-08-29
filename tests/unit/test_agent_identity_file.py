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


def test_failed_publish_leaves_existing_file_intact(tmp_path, monkeypatch):
    """A crash during re-mint must not truncate the identity file.

    The pre-fix implementation opened the target with O_TRUNC directly, so a
    crash mid-write bricked the identity at 0 bytes. The temp-file +
    os.replace design keeps the old value readable until the publish step,
    and a later call heals the corrupt state instead of failing forever.
    """
    home = tmp_path
    load_or_create_agent_id(home)  # establish a working layout
    path = home / "agent-peer" / "agent_id"
    path.write_text("not-a-uuid")  # force the re-mint branch

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated crash before publish")

    monkeypatch.setattr(os, "replace", boom)
    try:
        load_or_create_agent_id(home)
        published_anyway = True
    except OSError:
        published_anyway = False
    assert not published_anyway
    # The failed attempt did not truncate what was on disk.
    assert path.read_text(encoding="utf-8").strip() == "not-a-uuid"

    monkeypatch.setattr(os, "replace", real_replace)
    healed = load_or_create_agent_id(home)
    uuid.UUID(healed)  # a valid fresh identity, persisted and reloadable
    assert read_agent_id(home) == healed


@pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "Windows st_mode reports 0o666 regardless of os.chmod, so the "
        "'refuse world-readable identity' contract is untestable there, "
        "not satisfied there"
    ),
)
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
