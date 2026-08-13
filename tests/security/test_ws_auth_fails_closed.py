"""RISKY-1: WebSocket auth must fail closed.

Repro at final SHA ffe3687: _ws_upgrade_authorized() returns True when
hermes_cli.web_server import fails, so a broken production import
bypasses authentication. Required:
- any import failure of the auth module rejects the upgrade (False),
- the real delegate (hermes_cli.web_server._ws_auth_ok) still decides
  when importable,
- tests stay injectable via monkeypatching, never via import-absence.
"""

from __future__ import annotations

import dashboard.plugin_api as api


class _FakeWS:
    """Minimal stand-in exposing the attributes the auth gate touches."""

    def __init__(self, scope=None):
        self.scope = scope or {"type": "websocket", "headers": []}


class TestWsAuthFailsClosed:
    def test_missing_auth_module_rejects(self, monkeypatch):
        """A missing/broken auth import must reject, not accept."""
        import builtins

        real_import = builtins.__import__

        def broken_import(name, *args, **kwargs):
            if name == "hermes_cli.web_server":
                raise ImportError("simulated broken dashboard import")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", broken_import)
        assert api._ws_upgrade_authorized(_FakeWS()) is False

    def test_auth_module_error_rejects(self, monkeypatch):
        """Any exception during auth import rejects the upgrade."""
        import builtins

        real_import = builtins.__import__

        def error_import(name, *args, **kwargs):
            if name == "hermes_cli.web_server":
                raise RuntimeError("simulated module init failure")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", error_import)
        assert api._ws_upgrade_authorized(_FakeWS()) is False

    def test_real_delegate_decides(self, monkeypatch):
        """When importable, the canonical _ws_auth_ok result is returned."""
        import sys
        import types

        fake_module = types.ModuleType("hermes_cli.web_server")
        fake_module._ws_auth_ok = lambda ws: True
        monkeypatch.setitem(sys.modules, "hermes_cli.web_server", fake_module)
        assert api._ws_upgrade_authorized(_FakeWS()) is True

        fake_module._ws_auth_ok = lambda ws: False
        assert api._ws_upgrade_authorized(_FakeWS()) is False

    def test_injectable_without_import_dependency(self, monkeypatch):
        """Tests can inject the auth decision directly; import failure must
        never be the mechanism that makes auth pass."""
        monkeypatch.setattr(api, "_ws_upgrade_authorized", lambda ws: False)
        assert api._ws_upgrade_authorized(_FakeWS()) is False
