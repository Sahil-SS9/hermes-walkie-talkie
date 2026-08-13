"""Hermes Peer configuration (HP-702): receiver-owned settings.

Read from ``plugins.entries.hermes-peer.settings`` in config.yaml:

```yaml
plugins:
  entries:
    hermes-peer:
      settings:
        inbound: accept      # accept | hold | refuse
        name: backend        # optional explicit alias
```

Invalid values fail configuration validation with a clear error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_peer.constants import (
    BROADCAST_TTL_SECONDS,
    DEFAULT_FANOUT_CONCURRENCY,
    DEFAULT_GROUP_CAP,
    HARD_GROUP_CAP,
    PROTOCOL_ID,
    PROTOCOL_ID_V2,
)
from agent_peer.models import Policy

PLUGIN_ID = "hermes-peer"
SETTINGS_KEY = "settings"

try:
    from hermes_cli.config import load_config as _load_config  # ty: ignore[unresolved-import]
except ImportError:  # pragma: no cover - dep-free test venv / non-Hermes host
    def _load_config() -> dict:
        return {}


@dataclass(frozen=True, slots=True)
class PeerConfig:
    """Validated plugin settings."""

    inbound: str = Policy.ACCEPT.value
    name: str = ""
    allow_gateway_injection: bool = False
    max_content_bytes: int = 32 * 1024
    protocols: tuple[str, ...] = (PROTOCOL_ID, PROTOCOL_ID_V2)
    capabilities: dict = field(default_factory=dict)
    group_cap: int = DEFAULT_GROUP_CAP
    fanout_concurrency: int = DEFAULT_FANOUT_CONCURRENCY
    broadcast_ttl_seconds: float = BROADCAST_TTL_SECONDS
    request_ttl_seconds: float = 600.0
    event_clients: int = 32
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, ctx) -> PeerConfig:
        """Load settings from the live Hermes config; fail clearly on bad values."""
        settings = _read_settings()
        inbound = settings.get("inbound", Policy.ACCEPT.value)
        if inbound not in {p.value for p in Policy}:
            raise ValueError(
                f"hermes-peer: invalid settings.inbound {inbound!r}; "
                f"expected one of {sorted(p.value for p in Policy)}"
            )
        name = settings.get("name", "")
        if name is not None and not isinstance(name, str):
            raise ValueError("hermes-peer: settings.name must be a string")
        allow_gateway = bool(settings.get("allow_gateway_injection", False))
        return cls(
            inbound=inbound,
            name=(name or "").strip(),
            allow_gateway_injection=allow_gateway,
            group_cap=_bounded_int(settings, "group_cap", DEFAULT_GROUP_CAP, 1, HARD_GROUP_CAP),
            fanout_concurrency=_bounded_int(settings, "fanout_concurrency", DEFAULT_FANOUT_CONCURRENCY, 1, 64),
            broadcast_ttl_seconds=_bounded_float(settings, "broadcast_ttl_seconds", BROADCAST_TTL_SECONDS, 10.0, 3600.0),
            request_ttl_seconds=_bounded_float(settings, "request_ttl_seconds", 600.0, 10.0, 86400.0),
            event_clients=_bounded_int(settings, "event_clients", 32, 1, 256),
            extra={k: v for k, v in settings.items() if k not in ("inbound", "name", "allow_gateway_injection", "group_cap", "fanout_concurrency", "broadcast_ttl_seconds", "request_ttl_seconds", "event_clients")},
        )


def _bounded_int(settings: dict, key: str, default: int, lo: int, hi: int) -> int:
    value = settings.get(key, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"hermes-peer: settings.{key} must be an integer") from exc
    if parsed < lo or parsed > hi:
        raise ValueError(f"hermes-peer: settings.{key} {parsed} outside {lo}..{hi}")
    return parsed


def _bounded_float(settings: dict, key: str, default: float, lo: float, hi: float) -> float:
    value = settings.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"hermes-peer: settings.{key} must be a number") from exc
    if parsed < lo or parsed > hi:
        raise ValueError(f"hermes-peer: settings.{key} {parsed} outside {lo}..{hi}")
    return parsed


def _read_settings() -> dict:
    try:
        cfg = _load_config() or {}
    except Exception:
        return {}
    entries = (cfg.get("plugins") or {}).get("entries") or {}
    entry = entries.get(PLUGIN_ID) or {}
    settings = entry.get(SETTINGS_KEY)
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        return {}
    return settings
