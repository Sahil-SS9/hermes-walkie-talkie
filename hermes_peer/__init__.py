"""hermes_peer — Hermes adapter for Agent Peer.

Thin Hermes-only layer over the harness-neutral :mod:`agent_peer` core.
Uses the public Hermes plugin API only (register_tool, register_command,
register_hook, inject_message); private-field fallback is banned (see
``docs/compatibility.md`` and the HP-710 structural test).

The plugin manifest declares ``entry: __init__.py``, so the Hermes plugin
loader imports THIS module and calls ``register(ctx)`` on it. The
implementation lives in :mod:`hermes_peer.plugin`; it is re-exported here so
clone-style installations (and the real-Hermes-binary E2E) load correctly
(F-05/REM-501).

Clone-style Hermes plugins are imported under ``hermes_plugins.<slug>`` and
the loader does NOT add the plugin directory to ``sys.path``. The
harness-neutral :mod:`agent_peer` core is a sibling package inside the plugin
directory, so we add our own directory to ``sys.path`` (idempotently) before
any sibling import. This is the same pattern real multi-package plugins use
and touches only plugin-owned paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

_plugin_dir = str(Path(__file__).resolve().parent.parent)
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from .plugin import get_manager, host_seam_supported, register  # noqa: E402, F401

__version__ = "0.1.0rc1"

__all__ = ["__version__", "get_manager", "host_seam_supported", "register"]
