"""Groups error/edge branches (P11.1 coverage).

Covers the fail-closed branches of GroupStore that normal-path tests do
not hit: non-string names, invalid Group construction, unique-name
collision, owner-fence delete miss, and empty member agent_id.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_peer.errors import ValidationError
from agent_peer.groups import Group, GroupStore, normalise_group_name
from agent_peer.store import MessageStore

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture()
def store() -> MessageStore:
    return MessageStore(Path(tempfile.mkdtemp()) / "g.sqlite3")


class TestGroupNameValidation:
    def test_non_string_name_rejected(self):
        with pytest.raises(ValidationError):
            normalise_group_name(7)  # type: ignore[arg-type]

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            normalise_group_name("   ")

    def test_overlong_name_rejected(self):
        with pytest.raises(ValidationError):
            normalise_group_name("x" * 65)

    def test_invalid_charset_rejected(self):
        with pytest.raises(ValidationError):
            normalise_group_name("bad name!")

    def test_normalise_strips_and_casefolds(self):
        assert normalise_group_name("  Team-Alpha  ") == "team-alpha"


class TestGroupConstruction:
    def test_group_bad_group_id(self):
        with pytest.raises(ValidationError):
            Group("", "name", A, "t", "t", 0)  # type: ignore[arg-type]

    def test_group_bad_owner(self):
        with pytest.raises(ValidationError):
            Group("g1", "name", "", "t", "t", 0)  # type: ignore[arg-type]


class TestGroupStoreBranches:
    def test_duplicate_name_raises_unique(self, store):
        gs = GroupStore(store)
        gs.create_group(A, "dup")
        with pytest.raises(ValidationError, match="already exists"):
            gs.create_group(B, "DUP")

    def test_delete_owner_fence_miss_returns_false(self, store):
        gs = GroupStore(store)
        gs.create_group(A, "team")
        assert gs.delete_group("team", owner_agent_id=B) is False

    def test_add_member_empty_agent_rejected(self, store):
        gs = GroupStore(store)
        with pytest.raises(ValidationError, match="non-empty"):
            gs.add_member("g1", "")

    def test_add_member_missing_group_false(self, store):
        gs = GroupStore(store)
        assert gs.add_member("no-such-group", A) is False
