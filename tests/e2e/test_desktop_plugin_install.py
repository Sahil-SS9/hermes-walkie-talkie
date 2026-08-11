"""Desktop plugin install E2E (P7.7, G6.9).

`hermes peer desktop install|status|remove` copies the compiled plugin.js
into the Desktop plugins door under a disposable HERMES_HOME. Install is
explicit; never auto-installed; removal is clean.
"""

from __future__ import annotations

import os

import pytest

from hermes_peer.desktop_install import (
    desktop_plugin_status,
    install_desktop_plugin,
    remove_desktop_plugin,
)

PLUGIN_DOOR = "desktop-plugins/hermes-peer/plugin.js"


def test_install_status_remove_roundtrip(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    # Not installed initially.
    assert desktop_plugin_status(home=home)["installed"] is False

    target = install_desktop_plugin(home=home)
    assert target == home / PLUGIN_DOOR
    assert target.exists()
    assert target.read_text().startswith("/**") or "createPlugin" in target.read_text()

    status = desktop_plugin_status(home=home)
    assert status["installed"] is True
    assert status["sha256_prefix"]

    assert remove_desktop_plugin(home=home) is True
    assert not (home / "desktop-plugins" / "hermes-peer").exists()
    assert remove_desktop_plugin(home=home) is False  # already removed


def test_install_requires_home():

    # No --home and no HERMES_HOME -> explicit error, never a surprise write.
    import hermes_peer.desktop_install as _di

    old = os.environ.get("HERMES_HOME")
    os.environ.pop("HERMES_HOME", None)
    try:
        with pytest.raises(ValueError):
            _di.install_desktop_plugin()
    finally:
        if old:
            os.environ["HERMES_HOME"] = old


def test_install_uses_env_home(tmp_path, monkeypatch):
    home = tmp_path / "env-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    target = install_desktop_plugin()
    assert target == home / PLUGIN_DOOR
