"""P2 scaffold smoke tests: package imports and plugin entry points."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_agent_peer_imports_without_hermes():
    import agent_peer

    assert agent_peer.PROTOCOL_ID == "agent-peer/1"


def test_agent_peer_has_no_hermes_dependency():
    """Structural check: the core must never import Hermes modules."""
    import agent_peer

    root = Path(agent_peer.__file__).parent
    forbidden = ("hermes_cli", "gateway", "tui_gateway", "cli", "run_agent")
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for mod in forbidden:
            assert f"import {mod}" not in text, f"{py} imports {mod}"
            assert f"from {mod}" not in text, f"{py} imports from {mod}"


def test_plugin_manifest_present():
    manifest = REPO_ROOT / "plugin.yaml"
    assert manifest.exists()
    text = manifest.read_text(encoding="utf-8")
    assert "name: hermes-peer" in text
    assert "0.1.0rc1" in text


def test_root_plugin_entry_exposes_register():
    """The repo-root __init__.py (plugin entry) exposes callable register()."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("hwt_root", REPO_ROOT / "__init__.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.register)

    class FakeCtx:
        def inject_message(self, content, role="user", *, mode="queue", target_session=None):
            return True

    mod.register(FakeCtx())  # must not raise


def test_hermes_peer_plugin_registers_on_supported_host():
    """register() is a no-op success on a host with the additive seam."""
    from hermes_peer import plugin

    class FakeCtx:
        def inject_message(self, content, role="user", *, mode="queue", target_session=None):
            return True

    plugin.register(FakeCtx())  # must not raise


def test_hermes_peer_plugin_warns_without_seam():
    """Unsupported hosts produce a clear warning, never a private fallback."""
    from hermes_peer import plugin

    class OldCtx:
        def inject_message(self, content, role="user"):
            return True

    assert plugin.host_seam_supported(OldCtx()) is False
    assert plugin.host_seam_supported(object()) is False
