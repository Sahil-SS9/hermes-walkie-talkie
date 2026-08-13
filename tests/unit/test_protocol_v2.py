"""V2 protocol payload tests (P3.4, ADR-0004): strict bounded JSON validation."""

from __future__ import annotations

import json

import pytest

from agent_peer.errors import ValidationError
from agent_peer.protocol_v2 import (
    MessagePayload,
    RequestCancelPayload,
    RequestPayload,
    RequestStatusPayload,
    decode_v2_payload,
)


def test_message_payload_roundtrip():
    p = MessagePayload(text="hello")
    content = p.to_content()
    assert json.loads(content)["text"] == "hello"
    decoded = decode_v2_payload("message", content)
    assert decoded.text == "hello"


def test_request_payload_roundtrip():
    p = RequestPayload(
        request_id="r1",
        sender_agent_id="a",
        recipient_agent_id="b",
        state="created",
        summary="do the thing",
    )
    decoded = decode_v2_payload("request", p.to_content())
    assert decoded.request_id == "r1"
    assert decoded.state == "created"


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        decode_v2_payload("broadcast", "{}")


def test_missing_fields_rejected():
    with pytest.raises(ValidationError):
        decode_v2_payload("message", '{"kind":"message"}')


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        decode_v2_payload("message", '{"kind":"message","text":"hi","evil":1}')


def test_wrong_kind_field_rejected():
    with pytest.raises(ValidationError):
        decode_v2_payload("message", '{"kind":"receipt","text":"hi"}')


def test_non_json_rejected():
    with pytest.raises(ValidationError):
        decode_v2_payload("message", "not-json")


def test_non_object_rejected():
    with pytest.raises(ValidationError):
        decode_v2_payload("message", "[1,2,3]")


def test_cancel_payload_roundtrip():
    p = RequestCancelPayload(request_id="r9")
    decoded = decode_v2_payload("request_cancel", p.to_content())
    assert decoded.request_id == "r9"


def test_status_payload_roundtrip():
    p = RequestStatusPayload(request_id="r2", state="in_progress", detail="halfway")
    decoded = decode_v2_payload("request_status", p.to_content())
    assert decoded.state == "in_progress"
    assert decoded.detail == "halfway"
