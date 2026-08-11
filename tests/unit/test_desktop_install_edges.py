"""Desktop installer edge branches (P11.1 coverage).

- Missing bundled asset must raise a clear error (never copy a stub).
- A missing style.css is tolerated (plugin.js is the contract);
  remove/status handle absent installs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import hermes_peer.desktop_install as di


def test_install_missing_bundle_raises(monkeypatch, tmp_path):
    missing = tmp_path / "assets" / "desktop"
    missing.mkdir(parents=True)

    def fake_bundle():
        return missing / "plugin.js"

    monkeypatch.setattr(di, "_bundled_plugin", fake_bundle)
    with pytest.raises(ValueError, match="missing"):
        di.install_desktop_plugin(home=tmp_path)


def test_install_missing_style_css_skipped(monkeypatch, tmp_path):
    assets = tmp_path / "assets" / "desktop"
    assets.mkdir(parents=True)
    (assets / "plugin.js").write_text("export default {};", encoding="utf-8")
    # style.css intentionally absent: only plugin.js is copied.

    def fake_bundle():
        return assets / "plugin.js"

    monkeypatch.setattr(di, "_bundled_plugin", fake_bundle)
    target = di.install_desktop_plugin(home=tmp_path)
    assert target.exists()
    assert not (tmp_path / "desktop-plugins" / di.PLUGIN_NAME / "style.css").exists()


def test_remove_absent_returns_false(tmp_path):
    assert di.remove_desktop_plugin(home=tmp_path) is False


def test_status_absent_reports_not_installed(tmp_path):
    status = di.desktop_plugin_status(home=tmp_path)
    assert status["installed"] is False
