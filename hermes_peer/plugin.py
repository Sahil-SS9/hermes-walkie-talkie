"""Hermes plugin registration for hermes_peer (P2 scaffold, extended in P7)."""

from __future__ import annotations

import inspect
import logging

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


def register(ctx) -> None:
    """Register the Hermes Peer plugin (tools/commands/hooks land in P7-P8)."""
    if not host_seam_supported(ctx):
        logger.warning(
            "hermes_peer: host Hermes lacks the additive inject_message seam "
            "(mode/target_session). Peer delivery is unavailable on this host; "
            "run `hermes peer doctor` for details. No private-field fallback is used."
        )
