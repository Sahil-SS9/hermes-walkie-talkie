"""Structural adapter-boundary tests (HP-710).

hermes_peer must use ONLY public Hermes APIs and the harness-neutral core:
- no imports from gateway / tui_gateway / cli / run_agent / agent internals;
- no private-field access tokens (`_cli_ref`, `_pending_input`,
  `_interrupt_queue`, `_sessions`, `_entries`, ...) anywhere in the adapter;
- no reimplementation of core policy/persistence/registry/transport logic
  (the adapter imports agent_peer for all of it).
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = HERE.parents[1] / "hermes_peer"

FORBIDDEN_IMPORTS = (
    "import gateway",
    "from gateway",
    "import tui_gateway",
    "from tui_gateway",
    "import cli",
    "from cli import",
    "import run_agent",
    "from run_agent",
    "import agent",
    "from agent",
    "import hermes_cli.plugins",
    "from hermes_cli.plugins",
)

# Private host internals the plugin must never touch (AP-006 ban).
FORBIDDEN_TOKENS = (
    "_cli_ref",
    "_pending_input",
    "_interrupt_queue",
    "_agent_running",
    "._sessions",
    "._entries",
    "_running_agents",
    "_pending_messages",
    "_gateway_loop",
    "_interrupt_busy_session",
    "_enqueue_fifo",
    "_handle_message",
)

ALLOWED_HERMES_IMPORTS = ("hermes_cli.config", "hermes_cli.profiles")


def _adapter_files() -> list[Path]:
    return [p for p in ADAPTER_ROOT.rglob("*.py") if p.name != "__init__.py"]


def test_no_forbidden_imports():
    import re

    patterns = [
        re.compile(r"^\s*(?:import|from)\s+gateway\b"),
        re.compile(r"^\s*(?:import|from)\s+tui_gateway\b"),
        re.compile(r"^\s*import\s+cli\b"),
        re.compile(r"^\s*from\s+cli\b"),
        re.compile(r"^\s*(?:import|from)\s+run_agent\b"),
        re.compile(r"^\s*(?:import|from)\s+agent\b(?!_peer)"),  # agent internals, not agent_peer
        re.compile(r"^\s*(?:import|from)\s+hermes_cli\.plugins\b"),
    ]
    violations = []
    for py in _adapter_files():
        for line in py.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and any(p.search(stripped) for p in patterns):
                violations.append(f"{py.name}: {stripped}")
    assert violations == [], violations


def test_no_private_host_field_access():
    violations = []
    for py in _adapter_files():
        text = py.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                violations.append(f"{py.name}: {token}")
    assert violations == [], violations


def test_hermes_imports_are_public_only():
    violations = []
    for py in _adapter_files():
        text = py.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if (
                stripped.startswith(("import ", "from "))
                and "hermes_cli" in stripped
                and not any(allow in stripped for allow in ALLOWED_HERMES_IMPORTS)
            ):
                violations.append(f"{py.name}: {stripped}")
    assert violations == [], violations


def test_core_logic_not_reimplemented():
    """The adapter delegates to agent_peer; it must not reimplement sockets,
    framing, registry writes or SQL."""
    violations = []
    for py in _adapter_files():
        text = py.read_text(encoding="utf-8")
        if "import socket" in text:
            violations.append(f"{py.name}: raw socket use")
        if "CREATE TABLE" in text:
            violations.append(f"{py.name}: raw SQL schema")
        if "selectors" in text:
            violations.append(f"{py.name}: selector reimplementation")
    assert violations == [], violations


def test_no_placeholders():
    for py in _adapter_files():
        text = py.read_text(encoding="utf-8")
        assert "TODO" not in text and "FIXME" not in text, f"{py.name} has placeholders"
