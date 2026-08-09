"""Hermes Walkie Talkie — Hermes plugin entry point.

This file lives at the repository root so that a GitHub-style plugin install
(``hermes plugins install owner/repo``) works without adding ``src/`` to
``sys.path``: the plugin directory itself is importable.

Hermes loads a directory plugin's ``__init__.py`` as
``hermes_plugins.<slug>`` with ``__path__`` set to the plugin directory, so
sibling packages must be imported RELATIVELY here (an absolute import would
fail because the plugin directory is not on ``sys.path``). A pip-installed
plugin (``hermes_agent.plugins`` entry point) imports ``hermes_peer.plugin``
directly and never uses this file; the absolute fallback covers dev
checkouts where the repo root is on ``sys.path``.
"""

from __future__ import annotations


def register(ctx) -> None:
    """Hermes plugin entry point (public plugin API only)."""
    try:
        from .hermes_peer.plugin import register as _register
    except ImportError:  # pragma: no cover - dev-checkout / entry-point mode
        from hermes_peer.plugin import register as _register  # type: ignore[no-redef]

    _register(ctx)


__all__ = ["register"]
