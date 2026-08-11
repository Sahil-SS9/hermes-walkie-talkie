"""Surface taxonomy unit tests (P3/P9.3 gate).

The Desktop surface must survive the platform->surface mapping — a desktop
session advertises Surface.DESKTOP, never the collapsed TUI label
(regression fix locked in during P9.3 E2E).
"""

from __future__ import annotations

from hermes_peer.sessions import _surface_of


def test_desktop_surface_preserved():
    assert _surface_of("desktop") == "desktop"


def test_cli_default():
    assert _surface_of(None) == "cli"
    assert _surface_of("") == "cli"
    assert _surface_of("cli") == "cli"


def test_tui_and_dashboard_collapse_to_tui():
    assert _surface_of("tui") == "tui"
    assert _surface_of("webui") == "tui"
    assert _surface_of("dashboard") == "tui"


def test_gateway_surface():
    assert _surface_of("gateway") == "gateway"
