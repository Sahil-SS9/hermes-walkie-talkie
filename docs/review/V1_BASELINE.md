# V1 Baseline Matrix

> Archived 11 August 2026 before any V1.1 edits.
> Candidate: `/home/kensei/worktrees/hermes-walkie-talkie-v1-1` @ `f6d45194e3a906c13a2449805976d4e151430437`

## Command

```bash
cd /home/kensei/worktrees/hermes-walkie-talkie-v1-1
uv sync --group dev
.venv/bin/python -m pytest -q
```

## Result

```
403 passed, 4 skipped in 30.20s
```

## Skips (expected)

| Test | Reason |
|------|--------|
| tests/e2e/test_surfaces.py:76 | could not import 'tui_gateway.server' — standalone repo has no Hermes core |
| tests/e2e/test_surfaces.py:123 | could not import 'gateway.run' — standalone repo has no Hermes core |
| tests/security/test_security_audit.py:84 | cannot chown in this environment |
| tests/unit/test_paths.py:43 | cannot chown in this environment |

## Runner

- OS: Linux (7.0.0-28-generic)
- Python: 3.12.3
- uv: 0.11.28
- Import check: `.venv/bin/python -c "import agent_peer; print(agent_peer.__file__)"` → worktree path (editable resolves to candidate, not canonical)
