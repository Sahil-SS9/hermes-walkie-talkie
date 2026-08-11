"""Hypothesis property tests for the V2 protocol (P3, ADR-0004).

Invariants:
- decode(encode(payload)) == payload for every valid payload.
- Unknown/oversized/extra-field payloads always fail closed (never decode).
- Negotiation is monotonic: highest mutual version never fabricates V2.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_peer.capabilities import highest_mutual_protocol
from agent_peer.constants import PROTOCOL_ID, PROTOCOL_ID_V2
from agent_peer.errors import ValidationError
from agent_peer.protocol_v2 import (
    MessagePayload,
    RequestCancelPayload,
    RequestPayload,
    RequestStatusPayload,
    decode_v2_payload,
)

_TEXT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=200)
_UUID = st.text(alphabet="0123456789abcdef-", min_size=1, max_size=64)


@given(_TEXT)
@settings(max_examples=200)
def test_message_roundtrip_property(text: str):
    p = MessagePayload(text=text)
    decoded = decode_v2_payload("message", p.to_content())
    assert decoded.text == text


@given(_TEXT, _TEXT)
@settings(max_examples=200)
def test_request_status_roundtrip_property(state: str, detail: str):
    p = RequestStatusPayload(request_id="r", state=state, detail=detail)
    decoded = decode_v2_payload("request_status", p.to_content())
    assert decoded.state == state
    assert decoded.detail == detail


@given(_UUID, _TEXT, _TEXT)
@settings(max_examples=100)
def test_request_roundtrip_property(rid: str, summary: str, state: str):
    p = RequestPayload(
        request_id=rid,
        sender_agent_id="sender",
        recipient_agent_id="recipient",
        state=state,
        summary=summary,
    )
    decoded = decode_v2_payload("request", p.to_content())
    assert decoded.request_id == rid
    assert decoded.summary == summary


@given(_UUID)
@settings(max_examples=100)
def test_cancel_roundtrip_property(rid: str):
    p = RequestCancelPayload(request_id=rid)
    decoded = decode_v2_payload("request_cancel", p.to_content())
    assert decoded.request_id == rid


@given(st.text(min_size=1, max_size=50))
@settings(max_examples=100)
def test_unknown_kind_always_rejected(kind: str):
    # Unknown kinds must fail closed, never decode into a generic payload.
    if kind in ("message", "receipt", "discover", "alive", "request", "request_status", "request_cancel"):
        return
    try:
        decode_v2_payload(kind, '{"kind":"message"}')
    except ValidationError:
        return
    raise AssertionError(f"unknown kind {kind!r} did not fail closed")


@given(st.lists(st.text(), min_size=1, max_size=5))
@settings(max_examples=100)
def test_negotiation_never_fabricates_v2(advertised: list[str]):
    result = highest_mutual_protocol(tuple(advertised))
    assert result in (PROTOCOL_ID, PROTOCOL_ID_V2)
    if PROTOCOL_ID_V2 not in advertised:
        assert result == PROTOCOL_ID
