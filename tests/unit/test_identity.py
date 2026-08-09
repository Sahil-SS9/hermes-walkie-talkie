"""RED tests for identity generation and alias persistence (AP-403)."""

from __future__ import annotations

import uuid

import pytest

from agent_peer.identity import AliasStore, generate_instance_id, generate_peer_id, host_metadata


class TestIdentityGeneration:
    def test_peer_ids_unique(self):
        ids = {generate_peer_id() for _ in range(200)}
        assert len(ids) == 200
        for value in ids:
            uuid.UUID(value)  # must parse

    def test_instance_ids_unique(self):
        ids = {generate_instance_id() for _ in range(200)}
        assert len(ids) == 200

    def test_peer_and_instance_ids_differ_in_kind(self):
        # peer_id is a UUIDv4 string; both are UUID-parseable.
        assert uuid.UUID(generate_peer_id()).version == 4
        assert uuid.UUID(generate_instance_id()).version == 4


class TestHostMetadata:
    def test_metadata_has_stable_fields(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        meta = host_metadata()
        assert "cwd" in meta and meta["cwd"]
        assert "hostname" in meta and meta["hostname"]
        assert "pid" in meta and meta["pid"] > 0
        assert "started_at" in meta

    def test_git_repo_root_and_branch(self, tmp_path, monkeypatch):
        import subprocess

        subprocess.run(["git", "init", "-q", "-b", "feature/test"], cwd=tmp_path, check=True)
        (tmp_path / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], cwd=tmp_path, check=True)
        monkeypatch.chdir(tmp_path)
        meta = host_metadata()
        assert meta["git_repo_root"] == str(tmp_path)
        assert meta["git_branch"] == "feature/test"


class TestAliasStore:
    def test_set_and_get_alias(self, tmp_path):
        store = AliasStore(tmp_path / "aliases.json")
        peer_id = str(uuid.uuid4())
        store.set_alias(peer_id, "backend")
        assert store.get_alias(peer_id) == "backend"

    def test_default_name_shape(self, tmp_path):
        store = AliasStore(tmp_path / "aliases.json")
        peer_id = str(uuid.uuid4())
        name = store.effective_name(peer_id, default_base="myrepo")
        assert name.startswith("myrepo-")
        assert len(name) > len("myrepo-")

    def test_alias_persists_across_instances(self, tmp_path):
        path = tmp_path / "aliases.json"
        peer_id = str(uuid.uuid4())
        AliasStore(path).set_alias(peer_id, "frontend")
        assert AliasStore(path).get_alias(peer_id) == "frontend"

    def test_invalid_alias_rejected(self, tmp_path):
        store = AliasStore(tmp_path / "aliases.json")
        peer_id = str(uuid.uuid4())
        with pytest.raises(ValueError):
            store.set_alias(peer_id, "bad name/with/slashes!")
        with pytest.raises(ValueError):
            store.set_alias(peer_id, "")

    def test_unknown_alias_returns_none(self, tmp_path):
        store = AliasStore(tmp_path / "aliases.json")
        assert store.get_alias(str(uuid.uuid4())) is None
