"""Hermes Desktop disk-plugin installer (P7.7, G6.2/G6.9).

``hermes peer desktop install|status|remove`` installs the COMPILED Desktop
plugin (``hermes_peer/assets/desktop/plugin.js``) into
``<HERMES_HOME>/desktop-plugins/hermes-peer/plugin.js`` — the exact disk
door the core ``loadRuntimePlugin`` scans. Installation is EXPLICIT only;
nothing auto-installs (G6.9). The plugin is never activated in a live app by
this command (P8.12).
"""

from __future__ import annotations

import shutil
from pathlib import Path

PLUGIN_NAME = "hermes-peer"


def _resolve_home(home: Path | None) -> Path:
    """Resolve the target HERMES_HOME (explicit arg, env, or error)."""
    if home is not None:
        return Path(home)
    import os

    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return Path(env_home)
    raise ValueError("no HERMES_HOME supplied (pass --home or set HERMES_HOME)")


def _bundled_plugin() -> Path:
    """The checked-in compiled plugin asset inside this package."""
    return Path(__file__).resolve().parent / "assets" / "desktop" / "plugin.js"


def install_desktop_plugin(*, home: Path | None = None) -> Path:
    """Copy the compiled plugin (plugin.js + style.css) into the Desktop
    plugins door.

    Returns the installed plugin.js path. Raises ValueError when the
    bundled asset is missing (the P8 build has not produced it yet).
    """
    target_home = _resolve_home(home)
    source_dir = _bundled_plugin().parent
    if not _bundled_plugin().exists():
        raise ValueError(
            f"bundled Desktop plugin asset missing: {_bundled_plugin()} — build it first (P8)"
        )
    dest_dir = target_home / "desktop-plugins" / PLUGIN_NAME
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in ("plugin.js", "style.css"):
        src = source_dir / name
        if src.exists():
            shutil.copyfile(src, dest_dir / name)
    return dest_dir / "plugin.js"


def remove_desktop_plugin(*, home: Path | None = None) -> bool:
    """Remove the installed plugin directory (if present)."""
    target_home = _resolve_home(home)
    dest_dir = target_home / "desktop-plugins" / PLUGIN_NAME
    if not dest_dir.exists():
        return False
    shutil.rmtree(dest_dir)
    return True


def desktop_plugin_status(*, home: Path | None = None) -> dict:
    """Report whether the Desktop plugin is installed and its asset hash."""
    target_home = _resolve_home(home)
    dest = target_home / "desktop-plugins" / PLUGIN_NAME / "plugin.js"
    if not dest.exists():
        return {"installed": False, "home": str(target_home)}
    import hashlib

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()[:16]
    return {"installed": True, "home": str(target_home), "plugin": str(dest), "sha256_prefix": digest}


__all__ = ["desktop_plugin_status", "install_desktop_plugin", "remove_desktop_plugin"]
