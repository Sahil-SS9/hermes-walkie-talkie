"""V2 protocol payload validation branches (P11.1 coverage).

Every malformed V2 payload must fail closed with ValidationError: oversize
content, non-JSON, wrong kind, missing/extra fields and wrong-typed
field values.
"""

from __future__ import annotations

import pytest

from agent_peer.errors import ValidationError
from agent_peer.protocol_v2 import (
    MAX_CONTENT_BYTES,
    DiscoverPayload,
    MessagePayload,
    ReceiptPayload,
    V2Payload,
)


class TestV2PayloadValidation:
    def test_oversize_content_rejected(self):
        class Big(V2Payload):
            kind = "big"
            _fields = ("blob",)

            def __init__(self, blob: str) -> None:
                self.blob = blob

        with pytest.raises(ValidationError):
            Big.from_content('{"kind": "big", "blob": "' + "x" * (MAX_CONTENT_BYTES + 1) + '"}')

    def test_non_json_rejected(self):
        with pytest.raises(ValidationError):
            MessagePayload.from_content("not-json{{")

    def test_non_object_rejected(self):
        with pytest.raises(ValidationError):
            MessagePayload.from_content('["message", "x"]')

    def test_kind_mismatch_rejected(self):
        with pytest.raises(ValidationError):
            MessagePayload.from_content('{"kind": "receipt", "text": "x"}')

    def test_missing_fields_rejected(self):
        with pytest.raises(ValidationError):
            MessagePayload.from_content('{"kind": "message"}')

    def test_unknown_fields_rejected(self):
        with pytest.raises(ValidationError):
            MessagePayload.from_content('{"kind": "message", "text": "x", "extra": 1}')

    def test_message_text_non_string(self):
        with pytest.raises(ValidationError):
            MessagePayload(text=7)  # type: ignore[arg-type]

    def test_receipt_state_non_string(self):
        with pytest.raises(ValidationError):
            ReceiptPayload(state=7)  # type: ignore[arg-type]

    def test_discover_nonce_non_string(self):
        with pytest.raises(ValidationError):
            DiscoverPayload(nonce=[])  # type: ignore[arg-type]

    def test_roundtrip(self):
        m = MessagePayload(text="hello")
        r = MessagePayload.from_content(m.to_content())
        assert r.text == "hello"
