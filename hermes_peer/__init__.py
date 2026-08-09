"""hermes_peer — Hermes adapter for Agent Peer.

Thin Hermes-only layer over the harness-neutral :mod:`agent_peer` core.
Uses the public Hermes plugin API only (register_tool, register_command,
register_hook, inject_message); private-field fallback is banned (see
``docs/compatibility.md`` and the HP-710 structural test).
"""

from __future__ import annotations

__version__ = "0.1.0rc1"

__all__ = ["__version__"]
