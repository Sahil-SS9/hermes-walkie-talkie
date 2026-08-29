"""Shared e2e support: portable default for the Hermes core checkout.

Used by e2e tests that spawn a real Hermes process. Kept inside the
plugin package (not ``tests/``) so test modules can import it whether or
not ``tests/`` is an importable package.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def default_hermes_core_root() -> str:
    """Portable default for the Hermes core checkout.

    Order:
    1. explicit ``HERMES_CORE_ROOT`` env (CI provisioning or dev override);
    2. the running interpreter's own Hermes install (editable checkout on
       dev boxes) — ``hermes_cli`` is the core package, so its parent
       directory is the repository root;
    3. the historical maintainer worktree path (last resort).

    The returned path may not exist; the ``require_hermes_core`` fixture
    skips when the resolved root has no usable checkout.
    """
    env = os.environ.get("HERMES_CORE_ROOT")
    if env:
        return env
    spec = importlib.util.find_spec("hermes_cli")
    if spec is not None and spec.origin:
        # <checkout>/hermes_cli/__init__.py -> <checkout>
        return str(Path(spec.origin).resolve().parents[1])
    return "/home/kensei/worktrees/hermes-walkie-talkie-core-remediation-r2"


def core_root_usable(root: Path) -> bool:
    """True when ``root`` contains a runnable Hermes core checkout."""
    # hermes_cli lives at the checkout root; run_agent.py is the legacy entry.
    return (root / "hermes_cli").is_dir() or (root / "run_agent.py").exists()
