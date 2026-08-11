"""Request model tests (P5.1, G4.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_peer.errors import ValidationError
from agent_peer.request_models import Request, new_request_id


def _request(**overrides) -> Request:
    now = datetime.now(UTC)
    base: dict = dict(
        request_id=new_request_id(),
        sender_agent_id="sender-agent",
        recipient_agent_id="recipient-agent",
        state="created",
        summary="do the thing",
        created_at=now.isoformat(),
        deadline=(now + timedelta(minutes=5)).isoformat(),
    )
    base.update(overrides)
    return Request(**base)


def test_request_basic():
    r = _request()
    assert r.state == "created"
    assert r.summary == "do the thing"
    assert r.idempotency_key == ""
    assert r.parent_request_id == ""


def test_request_with_all_fields():
    r = _request(
        idempotency_key="key-1",
        correlation_id="corr-1",
        parent_request_id="parent-1",
        payload={"detail": "x"},
    )
    assert r.idempotency_key == "key-1"
    assert r.payload == {"detail": "x"}


def test_request_requires_ids():
    with pytest.raises(ValidationError):
        _request(request_id="")
    with pytest.raises(ValidationError):
        _request(sender_agent_id="")
    with pytest.raises(ValidationError):
        _request(recipient_agent_id="")


def test_request_rejects_unknown_state():
    with pytest.raises(ValidationError):
        _request(state="bogus")


def test_request_expiry():
    now = datetime.now(UTC)
    expired = _request(deadline=(now - timedelta(seconds=1)).isoformat())
    live = _request(deadline=(now + timedelta(seconds=60)).isoformat())
    assert expired.is_expired
    assert not live.is_expired


def test_new_request_id_unique():
    assert new_request_id() != new_request_id()
