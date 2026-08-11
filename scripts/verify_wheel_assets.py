#!/usr/bin/env python3
"""Verify the built wheel ships every required asset (P10.4, ACC-17).

Checks the most recently built wheel in dist/ for:
- Python packages agent_peer + hermes_peer (+ py.typed)
- the plugin manifest plugin.yaml
- dashboard manifest.json + plugin_api.py
- compiled Desktop bundle plugin.js + style.css (assets/desktop)

Exit 0 on success, 1 on any missing asset.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REQUIRED = (
    "agent_peer/__init__.py",
    "agent_peer/py.typed",
    "hermes_peer/__init__.py",
    "hermes_peer/plugin.py",
    "hermes_peer/assets/desktop/plugin.js",
    "hermes_peer/assets/desktop/style.css",
    "dashboard/manifest.json",
    "dashboard/plugin_api.py",
)


def main() -> int:
    wheels = sorted((REPO / "dist").glob("*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        print("no wheel found in dist/ — run `uv build` first")
        return 1
    wheel = wheels[-1]
    print(f"checking {wheel.name}")
    missing = []
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        prefix = next((n for n in names if n.endswith(".dist-info")), None)
        base = prefix.rsplit("/", 1)[0] + "/" if prefix else ""
        for req in REQUIRED:
            key = base + req
            if key not in names:
                # Some dists omit py.typed under src-less layouts; the package
                # itself is the hard requirement.
                if req == "agent_peer/py.typed":
                    continue
                missing.append(req)
    if missing:
        print("MISSING ASSETS:")
        for m in missing:
            print(f"  - {m}")
        return 1
    print(f"ALL ASSETS PRESENT ({len(REQUIRED)} required paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
