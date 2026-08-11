"""Persistent group CRUD tests (P4.1..P4.3, G3.1..G3.4)."""

from __future__ import annotations

import uuid

import pytest

from agent_peer.errors import ValidationError
from agent_peer.groups import GroupStore, normalise_group_name
from agent_peer.store import MessageStore


@pytest.fixture()
def group_store(tmp_path):
    store = MessageStore(tmp_path / "messages.sqlite3")
    g = GroupStore(store)
    yield g
    store.close()


def _agent() -> str:
    return str(uuid.uuid4())


def test_create_group_unique_name(group_store):
    owner = _agent()
    g1 = group_store.create_group(owner, "My Group")
    assert g1.name == "my group"
    # A normalised duplicate must be rejected (G3.1 unique normalised name).
    with pytest.raises(ValidationError):
        group_store.create_group(owner, "MY GROUP")


def test_group_name_normalisation():
    assert normalise_group_name("  Alpha  ") == "alpha"
    assert normalise_group_name("Backend-1") == "backend-1"
    with pytest.raises(ValidationError):
        normalise_group_name("")
    with pytest.raises(ValidationError):
        normalise_group_name("bad name!")
    with pytest.raises(ValidationError):
        normalise_group_name("x" * 65)


def test_get_by_id_and_name(group_store):
    owner = _agent()
    g = group_store.create_group(owner, "team-a")
    assert group_store.get_group(g.group_id).name == "team-a"
    assert group_store.get_group_by_name("TEAM-A").group_id == g.group_id
    assert group_store.get_group_by_name("missing") is None


def test_rename_with_optimistic_revision(group_store):
    owner = _agent()
    g = group_store.create_group(owner, "old-name")
    renamed = group_store.rename_group(g.group_id, "new-name", expected_revision=g.revision)
    assert renamed is not None
    assert renamed.name == "new-name"
    assert renamed.revision == g.revision + 1
    # Stale writer loses.
    stale = group_store.rename_group(g.group_id, "stale-name", expected_revision=g.revision)
    assert stale is None


def test_membership_crud(group_store):
    owner = _agent()
    g = group_store.create_group(owner, "members")
    a1, a2 = _agent(), _agent()
    assert group_store.add_member(g.group_id, a1) is True
    assert group_store.add_member(g.group_id, a2, peer_id=str(uuid.uuid4())) is True
    # Idempotent re-add.
    assert group_store.add_member(g.group_id, a1) is True
    members = group_store.members(g.group_id)
    assert len(members) == 2
    assert group_store.member_count(g.group_id) == 2
    assert group_store.remove_member(g.group_id, a1) is True
    assert group_store.member_count(g.group_id) == 1


def test_add_member_unknown_group_returns_false(group_store):
    assert group_store.add_member(str(uuid.uuid4()), _agent()) is False


def test_delete_group_cascades_members(group_store):
    owner = _agent()
    g = group_store.create_group(owner, "cascade")
    group_store.add_member(g.group_id, _agent())
    assert group_store.delete_group(g.group_id, owner_agent_id=owner) is True
    assert group_store.get_group(g.group_id) is None
    assert group_store.member_count(g.group_id) == 0


def test_delete_group_owner_fence(group_store):
    owner = _agent()
    g = group_store.create_group(owner, "fenced")
    # Wrong owner cannot delete.
    assert group_store.delete_group(g.group_id, owner_agent_id=_agent()) is False
    assert group_store.get_group(g.group_id) is not None


def test_member_cap_enforced(group_store):
    with pytest.raises(ValidationError):
        group_store.validate_cap(30, cap=30)  # 30 + 1 > 30
    group_store.validate_cap(29, cap=30)  # ok
    with pytest.raises(ValidationError):
        group_store.validate_cap(0, cap=0)  # cap below 1
    with pytest.raises(ValidationError):
        group_store.validate_cap(0, cap=129)  # above hard ceiling
