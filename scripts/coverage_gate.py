#!/usr/bin/env python3
"""Deterministic coverage gate (SEC-1015).

Runs the full suite with branch coverage and asserts:
- >= 90% line coverage across agent_peer + hermes_peer;
- >= 85% branch coverage on the trust/delivery path modules — the
  components that handle untrusted wire input and message delivery:
  codec, discovery, models, policy, registry, runtime, store, transport,
  delivery.

The gate consumes coverage.py's JSON counters. The terminal ``Cover`` column
combines statements and branches and ``BrPart`` is only partial branches, so
neither is a valid numerator for these two independent contracts.

Usage:
    uv run python scripts/coverage_gate.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / ".coverage-gate.json"

LINE_MIN = 90.0
BRANCH_MIN = 85.0
TRUST_DELIVERY_MODULES = (
    "agent_peer.codec",
    "agent_peer.discovery",
    "agent_peer.models",
    "agent_peer.policy",
    "agent_peer.registry",
    "agent_peer.runtime",
    "agent_peer.store",
    "agent_peer.transport",
    "hermes_peer.delivery",
)


def _module_summary(files: dict, module: str) -> dict | None:
    key = module.replace(".", "/") + ".py"
    row = files.get(key)
    if row is None:
        row = next((value for path, value in files.items() if path.endswith(key)), None)
    if not isinstance(row, dict):
        return None
    summary = row.get("summary")
    return summary if isinstance(summary, dict) else None


def main() -> int:
    REPORT.unlink(missing_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "--cov=agent_peer",
        "--cov=hermes_peer",
        "--cov-branch",
        "--cov-report=term",
        f"--cov-report=json:{REPORT}",
    ]
    env = dict(os.environ)
    import_roots = [str(REPO)]
    core_root = env.get("HERMES_CORE_ROOT", "").strip()
    if core_root:
        import_roots.append(core_root)
    inherited = env.get("PYTHONPATH", "").strip()
    if inherited:
        import_roots.append(inherited)
    env["PYTHONPATH"] = os.pathsep.join(import_roots)

    proc = subprocess.run(
        cmd,
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    out = proc.stdout + proc.stderr
    failures: list[str] = []
    if proc.returncode != 0:
        failures.append(f"test suite exited {proc.returncode}")

    try:
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        print(out[-5000:])
        print(f"COVERAGE GATE: FAIL (invalid JSON report: {exc})")
        return 1
    finally:
        REPORT.unlink(missing_ok=True)

    totals = payload.get("totals", {})
    files = payload.get("files", {})
    num_statements = int(totals.get("num_statements", 0))
    covered_lines = int(totals.get("covered_lines", 0))
    if num_statements <= 0:
        print(out[-5000:])
        print("COVERAGE GATE: FAIL (no measured statements)")
        return 1

    line_pct = 100.0 * covered_lines / num_statements
    if line_pct < LINE_MIN:
        failures.append(f"line coverage {line_pct:.1f}% < {LINE_MIN}%")

    branch_total = 0
    branch_covered = 0
    detail: list[str] = []
    for module in TRUST_DELIVERY_MODULES:
        summary = _module_summary(files, module)
        if summary is None:
            failures.append(f"coverage row missing for {module}")
            continue
        module_total = int(summary.get("num_branches", 0))
        module_covered = int(summary.get("covered_branches", 0))
        branch_total += module_total
        branch_covered += module_covered
        detail.append(f"{module}: {module_covered}/{module_total} branches")

    if branch_total <= 0:
        failures.append("trust/delivery branch denominator is zero")
        branch_pct = 0.0
    else:
        branch_pct = 100.0 * branch_covered / branch_total
        if branch_pct < BRANCH_MIN:
            failures.append(
                f"trust/delivery branch coverage {branch_pct:.1f}% < {BRANCH_MIN}%"
            )

    print(
        "trust/delivery branch coverage: "
        f"{branch_pct:.1f}% ({branch_covered}/{branch_total})"
    )
    for row in detail:
        print(f"  {row}")
    print(f"overall line coverage: {line_pct:.1f}% ({covered_lines}/{num_statements})")

    if failures:
        if proc.returncode != 0:
            print("\n--- pytest tail ---")
            print(out[-5000:])
        print("COVERAGE GATE: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("COVERAGE GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
