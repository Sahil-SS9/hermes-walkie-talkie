"""Config ceiling validation tests (P6.7, G1.6)."""

from __future__ import annotations

import pytest

from agent_peer.constants import DEFAULT_FANOUT_CONCURRENCY, DEFAULT_GROUP_CAP, HARD_GROUP_CAP
from hermes_peer.config import PeerConfig


class _Ctx:
    pass


def _cfg_with(settings: dict) -> PeerConfig:
    import hermes_peer.config as cfgmod

    original = cfgmod._read_settings
    cfgmod._read_settings = lambda: settings
    try:
        return PeerConfig.load(_Ctx())
    finally:
        cfgmod._read_settings = original


def test_defaults():
    cfg = _cfg_with({})
    assert cfg.group_cap == DEFAULT_GROUP_CAP
    assert cfg.fanout_concurrency == DEFAULT_FANOUT_CONCURRENCY
    assert cfg.broadcast_ttl_seconds > 0
    assert cfg.request_ttl_seconds > 0
    assert cfg.event_clients == 32


def test_group_cap_within_hard_ceiling():
    assert _cfg_with({"group_cap": 100}).group_cap == 100
    assert _cfg_with({"group_cap": HARD_GROUP_CAP}).group_cap == HARD_GROUP_CAP
    with pytest.raises(ValueError):
        _cfg_with({"group_cap": HARD_GROUP_CAP + 1})
    with pytest.raises(ValueError):
        _cfg_with({"group_cap": 0})
    with pytest.raises(ValueError):
        _cfg_with({"group_cap": "many"})


def test_fanout_concurrency_bounded():
    assert _cfg_with({"fanout_concurrency": 16}).fanout_concurrency == 16
    with pytest.raises(ValueError):
        _cfg_with({"fanout_concurrency": 0})
    with pytest.raises(ValueError):
        _cfg_with({"fanout_concurrency": 1000})


def test_ttl_bounds():
    assert _cfg_with({"broadcast_ttl_seconds": 120}).broadcast_ttl_seconds == 120
    with pytest.raises(ValueError):
        _cfg_with({"broadcast_ttl_seconds": 1})
    with pytest.raises(ValueError):
        _cfg_with({"request_ttl_seconds": 1})


def test_event_clients_bounded():
    assert _cfg_with({"event_clients": 64}).event_clients == 64
    with pytest.raises(ValueError):
        _cfg_with({"event_clients": 0})
    with pytest.raises(ValueError):
        _cfg_with({"event_clients": 100000})


def test_unknown_settings_land_in_extra():
    cfg = _cfg_with({"custom": "x"})
    assert cfg.extra == {"custom": "x"}
