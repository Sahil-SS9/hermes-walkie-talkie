"""Tool-schema budget test (P7 gate).

The consolidated plugin tool surface must stay bounded — V1's three tools
plus the V2 consolidated request/group tools. Every tool carries the
hermes-peer toolset (no redundant core tool) and the plugin remains
unloadable (disposers returned, no core files touched).
"""

from __future__ import annotations

import json

from hermes_peer import tools


def _registered_tools():
    """Collect tools registered by register_tools against a fake ctx."""
    captured: dict[str, dict] = {}

    class Ctx:
        def register_tool(self, name, *, toolset, schema, handler, description, emoji):
            captured[name] = {
                "toolset": toolset,
                "schema": schema,
                "handler": handler,
                "description": description,
            }

    tools.register_tools(Ctx())
    return captured


def test_tool_count_and_schema_budget():
    registered = _registered_tools()
    # V1 three + V2 consolidated request (4) + group (3) = 10 total.
    assert len(registered) == 10
    v1 = {"peer_list_agents", "peer_send_message", "peer_read_inbox"}
    v2 = {
        "peer_request_create",
        "peer_request_status",
        "peer_request_respond",
        "peer_request_cancel",
        "peer_group_list",
        "peer_group_manage",
        "peer_broadcast",
    }
    assert set(registered) == v1 | v2
    # Every tool is plugin-scoped; no tool lands in a core toolset.
    for name, spec in registered.items():
        assert spec["toolset"] == "hermes-peer", f"{name} not hermes-peer-scoped"


def test_schema_bytes_bounded():
    """Schemas stay small — the model pays for them every turn."""
    registered = _registered_tools()
    total_bytes = sum(len(json.dumps(spec["schema"])) for spec in registered.values())
    # 10 compact schemas must stay well under 4 KiB aggregate.
    assert total_bytes < 4096, f"tool schema budget exceeded: {total_bytes} bytes"


def test_no_tool_touches_core_files():
    """P7 gate: the plugin registers tools through ctx only; it must not
    import or modify Hermes core internals."""
    import inspect

    src = inspect.getsource(tools)
    for forbidden in ("hermes_cli.tools", "run_agent.", "tui_gateway.", "gateway.run"):
        assert forbidden not in src, f"tool module references core {forbidden!r}"
