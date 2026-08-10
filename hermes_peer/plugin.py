"""Hermes plugin registration for hermes_peer (P7; tools/commands land in P8)."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sessions import PeerSessionManager

logger = logging.getLogger("hermes_peer")

_SEAM_KWARGS = ("mode", "target_session")


def host_seam_supported(ctx) -> bool:
    """Return True when the host exposes the additive inject_message seam.

    Feature detection per docs/compatibility.md: the plugin never falls back
    to private Hermes fields — an unsupported host produces a clear doctor
    error instead.
    """
    fn = getattr(ctx, "inject_message", None)
    if fn is None:
        return False
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    params = sig.parameters
    return "mode" in params and "target_session" in params


# Process-global adapter state (one supervisor per process).
_manager: PeerSessionManager | None = None


def get_manager() -> PeerSessionManager | None:
    """Return the process-global PeerSessionManager (None before register)."""
    return _manager


def register(ctx) -> None:
    """Register the Hermes Peer plugin: config, lifecycle hooks, delivery."""
    global _manager
    if _manager is not None:
        return  # already registered in this process

    if not host_seam_supported(ctx):
        logger.warning(
            "hermes_peer: host Hermes lacks the additive inject_message seam "
            "(mode/target_session). Peer delivery is unavailable on this host; "
            "run `hermes peer doctor` for details. No private-field fallback is used."
        )
        # Still register lifecycle hooks so presence/registry work once the
        # host is upgraded; delivery stays disabled (fail closed).

    from .config import PeerConfig
    from .sessions import PeerSessionManager

    config = PeerConfig.load(ctx)
    manager = PeerSessionManager(ctx, config=config)

    ctx.register_hook("on_session_open", manager.on_session_open)
    ctx.register_hook("on_session_start", manager.on_session_start)
    ctx.register_hook("on_session_end", manager.on_session_end)
    ctx.register_hook("on_session_reset", manager.on_session_reset)
    ctx.register_hook("on_session_finalize", manager.on_session_finalize)

    from .commands import register_commands
    from .tools import register_tools

    register_tools(ctx)
    register_commands(ctx)

    _manager = manager
    logger.info(
        "hermes_peer: registered (inbound=%s, seam=%s)",
        config.inbound,
        host_seam_supported(ctx),
    )
