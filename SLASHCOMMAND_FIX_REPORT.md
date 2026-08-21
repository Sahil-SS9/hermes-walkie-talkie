# Slash-Command Interactive UX — Investigation & Fix Report

Date: 2026-08-21
Scope: Walkie-Talkie plugin (hermes-walkie-talkie) + Hermes host CLI (KenseiAgent)

## Issues found

### 1. Multi-session Rename/Policy actions always failed (functional bug)
**Symptom**: `/peers` → pick a peer → Rename or "Set policy" returned
`"Rename failed: no session_id supplied and multiple sessions active"` /
`"Policy failed: ..."` whenever more than one session was registered.
**Root cause**: the per-peer action closures called `mgr.set_alias(name)` /
`mgr.set_policy(policy)` with no session binding. The manager requires an
explicit `session_id` when multiple sessions exist, and `/peers` exists
precisely to manage multiple sessions.
**Fix**: `cmd_peers` captures `session_id` from kwargs and threads it into
every mutating closure; added `_bind_sid()` and threaded `session_id`
through all guided-flow handlers (`_rename_handler`, `_policy_handler`,
`_group_create/_add/_delete_handler`, `_request_*_handler`).

### 2. Misleading per-peer "Set policy" label
**Root cause**: policy is session-scoped in this codebase, but the sub-menu
claimed to set the *selected peer's* policy.
**Fix**: relabeled to "Set MY inbound policy" (action + sub-menu title) so the
UI is honest about what it changes.

### 3. Empty session_id became a bogus lookup (host)
**Root cause**: the dispatch passed `session_id=""` when the host had no
session id; the manager treats `""` as an explicit (invalid) session.
**Fix**: dispatch normalizes to `None` (`str(...) or None`).

### 4. Free-text prompts silently cancelled in the live TUI (critical UX bug)
**Symptom**: the reported "returns to chat" behaviour — selecting Send,
Rename, Create group, request create, or broadcast compose dumped the user
back to chat with no prompt and no feedback.
**Root cause**: `_prompt_text_input` returned `None` immediately on the
slash-worker daemon thread when the TUI app was running (a deliberate guard
added for a billing-terminal hang). Every free-text step in the interactive
engine used this path.
**Fix**: new `_prompt_free_text_modal()` schedules a visible modal on the
app loop via `call_soon_threadsafe` (same threading model as the proven
`_secret_state` path); Enter submits the typed text; ESC/Ctrl+C cancels.
The engine's prompt actions now use it. A visible panel tells the user
"Type your input below, then press Enter. ESC or Ctrl+C to cancel."

### 5. No usage capture
**Fix**: `_usage_log()` appends JSONL to `<runtime_root>/command-usage.jsonl`
on every command invocation; new `hermes peer usage --limit N` subcommand
displays recent records.

### 6. Documentation mis-stated completion behaviour
**Fix**: INTERACTION_GUIDE.md now documents the one-shot completion model
(pick → act → return to chat; re-invoke for another action), the free-text
modal, and the usage command.

## Navigation / exit / footprint (items 1-3) — verified
- Navigation: choice pickers (curses) + free-text modal both work from the
  slash-worker thread; verified via mocked flows.
- Exit: completing an action returns to chat with only the intended result
  printed — verified (no loop-back, no unexpected extra output).
- Footprint: the host dispatch ignores `_run_interactive_spec`'s return
  value, so no value leaks into the chat; `_cprint` is the standard clean
  renderer. Verified by `test_esc_at_root_exits_cleanly` (zero output) and
  `test_full_send_flow_returns_to_chat_with_result` (exactly one line).

## Changes made

hermes-walkie-talkie @ 42bb6b3
- `hermes_peer/commands.py`: session binding everywhere, usage logging,
  `hermes peer usage`, policy label honesty, UTC alias.
- `INTERACTION_GUIDE.md`: corrected completion model + usage section.
- `tests/unit/test_interactive_regressions.py` (new, 4 tests).

KenseiAgent @ 1d06924c8b
- `cli.py`: `_prompt_free_text_modal`, `_submit_free_text_response`,
  `_free_text_state` lifecycle, Enter binding, free-text render panel wired
  into the TUI layout, engine prompt actions use the modal, empty session_id
  normalization.
- `tests/cli/test_interactive_spec_engine.py`: +1 modal-routing test.
- `tests/cli/test_interactive_uiux_flows.py` (new, 4 UI/UX flow tests).

## Test coverage

hermes-walkie-talkie (772 passed / 31 skipped, ruff clean):
- `test_interactive_regressions.py` — multi-session rename/policy binding,
  usage-log write, usage CLI display.
- Existing suites (hermes_commands, cli_v1_1, tool_command_coverage,
  dashboard_api, sessions edge branches) all green.

KenseiAgent (49 passed in targeted run; full host suite 84 passed):
- `test_interactive_spec_engine.py` (5) — item detail, prompt→text via modal,
  children→value, Esc exit, handler→string.
- `test_interactive_uiux_flows.py` (4) — full send flow, Esc clean exit,
  empty-text cancel, repeated-invocation consistency.
- Existing host CLI/TUI/skin/prompt suites green; cli.py AST parse OK.

## Remaining limitations
- The free-text modal and picker were verified with mocked I/O and unit
  tests; a live interactive TUI session (real keystrokes) has not been run
  in this environment — recommended before shipping the UX to end users.
- The Electron desktop plugin and dashboard rail still render flat output;
  the interactive menu model is CLI/TUI-only for now.
- `hermes peer usage` shows recent records from the JSONL log; there is no
  retention/rotation policy yet (log grows unbounded).
- Per-peer policy editing does not exist in the data model; "Set MY inbound
  policy" is the honest label for the session-scoped operation.
