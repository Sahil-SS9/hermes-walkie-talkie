"""Capability negotiation tests (P3.3, P3.5, ADR-0004)."""

from __future__ import annotations

from agent_peer.capabilities import (
    capability_flag,
    highest_mutual_protocol,
    supports_v2,
)
from agent_peer.constants import PROTOCOL_ID, PROTOCOL_ID_V2


def test_missing_advertisement_fails_closed_to_v1():
    assert highest_mutual_protocol(None) == PROTOCOL_ID
    assert highest_mutual_protocol(()) == PROTOCOL_ID


def test_v1_peer_negotiates_v1():
    assert highest_mutual_protocol((PROTOCOL_ID,)) == PROTOCOL_ID


def test_v2_peer_negotiates_highest_mutual():
    assert highest_mutual_protocol((PROTOCOL_ID, PROTOCOL_ID_V2)) == PROTOCOL_ID_V2


def test_unknown_only_advertisement_fails_closed_to_v1():
    assert highest_mutual_protocol(("agent-peer/9",)) == PROTOCOL_ID


def test_supports_v2():
    assert supports_v2((PROTOCOL_ID, PROTOCOL_ID_V2)) is True
    assert supports_v2((PROTOCOL_ID,)) is False
    assert supports_v2(None) is False


def test_capability_flag():
    assert capability_flag({"groups": True}, "groups") is True
    assert capability_flag({"groups": False}, "groups") is False
    assert capability_flag({}, "groups") is False
    assert capability_flag(None, "groups") is False
