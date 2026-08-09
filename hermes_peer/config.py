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
            extra={k: v for k, v in settings.items() if k not in ("inbound", "name", "allow_gateway_injection")},
        )


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
