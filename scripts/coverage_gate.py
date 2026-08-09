#!/usr/bin/env python3
"""Deterministic coverage gate (SEC-1015).

Runs the full suite with branch coverage and asserts:
- >= 90% LINE coverage across agent_peer + hermes_peer;
- >= 85% BRANCH coverage on the trust/delivery path modules — the
  components that handle untrusted wire input and message delivery:
  codec, models, policy, registry, runtime, store, transport, delivery.

Usage:
    uv run python scripts/coverage_gate.py
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import suppress
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

LINE_MIN = 90.0
BRANCH_MIN = 85.0
TRUST_DELIVERY_MODULES = (
    "agent_peer.codec",
    "agent_peer.models",
    "agent_peer.policy",
    "agent_peer.registry",
    "agent_peer.runtime",
    "agent_peer.store",
    "agent_peer.transport",
    "hermes_peer.delivery",
)


def main() -> int:
    cmd = [
        sys.executable, "-m", "pytest", "-q", "--no-header",
        "--cov=agent_peer", "--cov=hermes_peer", "--cov-branch",
        "--cov-report=term",
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1800)
    out = proc.stdout + proc.stderr
    failures: list[str] = []

    # Parse the per-module table.
    per_module: dict[str, dict] = {}
    totals: dict = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 6 and parts[0].endswith(".py"):
            try:
                per_module[parts[0]] = {
                    "stmts": int(parts[1]), "miss": int(parts[2]),
                    "branch": int(parts[3]), "brpart": int(parts[4]),
                    "cover": float(parts[5].rstrip("%")),
                }
            except ValueError:
                continue
        if line.startswith("TOTAL"):
            parts = line.split()
            if len(parts) >= 6:
                with suppress(ValueError):
                    totals = {
                        "stmts": int(parts[1]), "miss": int(parts[2]),
                        "branch": int(parts[3]), "brpart": int(parts[4]),
                        "cover": float(parts[5].rstrip("%")),
                    }

    if not totals:
        print(out[-3000:])
        print("COVERAGE GATE: FAIL (could not parse coverage output)")
        return 1

    line_pct = totals["cover"]
    if line_pct < LINE_MIN:
        failures.append(f"line coverage {line_pct:.1f}% < {LINE_MIN}%")

    # Branch coverage on trust/delivery path modules only.
    branch_total = 0
    branch_partial = 0
    missing: list[str] = []
    for mod in TRUST_DELIVERY_MODULES:
        # The report key is the file path (e.g. agent_peer/codec.py).
        key = mod.replace(".", "/") + ".py"
        row = per_module.get(key)
        if row is None:
            # Module may not have been imported; fall back to searching the
            # table for the file name.
            row = next((r for k, r in per_module.items() if k.endswith(key)), None)
        if row is None:
            failures.append(f"coverage row missing for {mod}")
            continue
        branch_total += row["branch"]
        branch_partial += row["brpart"]
        missing.append(f"{mod}: {row['branch'] - row['brpart']}/{row['branch']} branches")
    if branch_total:
        branch_pct = 100.0 * (branch_total - branch_partial) / branch_total
        if branch_pct < BRANCH_MIN:
            failures.append(f"trust/delivery branch coverage {branch_pct:.1f}% < {BRANCH_MIN}%")
        print(f"trust/delivery branch coverage: {branch_pct:.1f}% ({branch_total - branch_partial}/{branch_total})")
        for m in missing:
            print(f"  {m}")

    print(f"overall line coverage: {line_pct:.1f}%")
    if failures:
        print("COVERAGE GATE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("COVERAGE GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
