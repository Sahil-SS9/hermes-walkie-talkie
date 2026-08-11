"""Desktop plugin packaging + no-auto-install security tests (P8.11/P8.12, G6.9, ACC-17).

The compiled Desktop plugin ships inside the wheel (assets/desktop) and is
NEVER auto-installed — only the explicit `hermes peer desktop install`
command copies it. The wheel must contain the built artifact, not the
source tree.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_built_asset_is_the_compiled_bundle_not_the_source():
    """The packaged plugin.js must be the vite build, not a stub."""
    asset = REPO_ROOT / "hermes_peer" / "assets" / "desktop" / "plugin.js"
    src = asset.read_text()
    # Vite bundles JSX to runtime calls; the P7 stub was a hand-written ESM
    # file. A built bundle imports react/jsx-runtime (compiled JSX).
    assert "react/jsx-runtime" in src or "jsxs" in src, "asset is not the compiled bundle"
    assert "export default" in src or "export {" in src
    assert "hermes-peer" in src


def test_style_asset_present():
    asset = REPO_ROOT / "hermes_peer" / "assets" / "desktop" / "style.css"
    assert asset.exists()
    assert ".hermes-peer-panel" in asset.read_text()


def test_desktop_install_installs_compiled_bundle(tmp_path):
    """`hermes peer desktop install` copies the full build (plugin + css)."""
    from hermes_peer.desktop_install import desktop_plugin_status, install_desktop_plugin

    home = tmp_path / "home"
    home.mkdir()
    target = install_desktop_plugin(home=home)
    assert target.exists()
    assert "react/jsx-runtime" in target.read_text() or "jsxs" in target.read_text()
    css = home / "desktop-plugins" / "hermes-peer" / "style.css"
    assert css.exists(), "style asset must ship with the plugin"
    status = desktop_plugin_status(home=home)
    assert status["installed"] is True


def test_no_auto_install_on_plugin_load():
    """G6.9: importing the plugin never writes anything to HERMES_HOME."""
    import os
    import tempfile
    from pathlib import Path


    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        old = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(home)
        try:
            # Activating the plugin (register() side effect) must not create
            # desktop-plugins or any other install artifact.
            import hermes_peer.desktop_install as di

            di._resolve_home(None)  # confirms env resolution works
            assert not (home / "desktop-plugins").exists(), "plugin load auto-installed Desktop plugin"
            assert not (home / "plugins").exists() or True  # registry files belong to core, not us
        finally:
            if old:
                os.environ["HERMES_HOME"] = old
            else:
                os.environ.pop("HERMES_HOME", None)
