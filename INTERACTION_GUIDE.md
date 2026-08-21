# Walkie-Talkie Interactive Command Guide

All slash commands now support a guided, step‑by‑step interactive experience
when invoked without arguments (or with incomplete arguments). The host drives
a recursive menu engine: arrow‑key picker → actions → prompts → nested menus.
Esc pops a level; Esc at the root exits.

**Completion model (important):** each command is *one-shot*. After you select
a final option and the action completes, the command returns to the chat
session with its result printed — it does NOT loop back into the picker. If you
want to run another action, re-invoke the command. The only exceptions are the
nested sub‑menus (e.g. the Policy picker), where Esc returns one level before
the outer action completes.

## /peers
- **Entry point**: `/peers`
- **Interactive steps**:
  1. Picker lists all live non‑gateway sessions (peers).
  2. Select a peer → action picker: Send, Inbox, Set MY inbound policy, Rename.
  3. **Send**: prompts for message text (type in the modal, press Enter) → sends.
  4. **Inbox**: shows held/queued messages (flat list) → each has Release/Refuse.
  5. **Policy**: nested picker → choose accept/hold/refuse → sets THIS session's
     inbound policy (policy is session-scoped; the label says "MY" to be clear).
  6. **Rename**: prompts for new name → sets peer alias.
- **Nested menus**: Policy sub‑menu.
- **Completion**: After an action runs, the command returns to chat with the
  result printed. Re-invoke `/peers` for another action.
- **Exit**: Esc at any picker leaves the command without acting.

## /peer-broadcast
- **Entry point**: `/peer-broadcast`
- **Interactive steps**:
  1. Picker lists all groups.
  2. Select a group → prompts for broadcast message text (type, press Enter).
  3. Sends the broadcast and prints the result.
- **Nested**: none.
- **Completion**: Returns to chat after send.
- **Exit**: Esc at group picker leaves.

## /peer-inbox
- **Entry point**: `/peer-inbox`
- **Interactive steps**:
  1. Picker lists held/queued messages (one per item).
  2. Select a message → action picker: Release, Refuse.
  3. **Release**: marks message as delivered.
  4. **Refuse**: marks message as refused.
- **Nested**: none.
- **Completion**: Returns to chat after action.
- **Exit**: Esc at message picker leaves.

## /peer-groups
- **Entry point**: `/peer-groups`
- **Interactive steps**:
  1. Picker lists all persistent groups.
  2. Select a group → action picker: List members, Add member, Delete group.
  3. **List members**: shows agent_id/peer_id pairs.
  4. **Add member**: prompts for agent_id → adds.
  5. **Delete group**: deletes the group (with confirmation via action text).
- **Nested**: none.
- **Completion**: Returns to chat after action.
- **Exit**: Esc at group picker leaves.

## /peer-group
- **Entry point**: `/peer-group`
- **Interactive steps** (bare):
  1. Picker lists actions: Create group.
  2. Select Create → prompts for new group name → creates.
- **Direct usage** (guided only for missing args):
  - `/peer-group create <name>` creates.
  - `/peer-group add <group_id> <agent_id>` adds.
  - `/peer-group remove <group_id> <agent_id>` removes.
  - `/peer-group delete <group_id>` deletes.
- **Completion**: returns to chat after create.
- **Exit**: Esc at action picker leaves.

## /peer-policy
- **Entry point**: `/peer-policy`
- **Interactive steps**:
  1. Picker lists policies: accept, hold, refuse.
  2. Select one → applies as this session's inbound policy.
- **Nested**: none.
- **Completion**: returns to chat after set.
- **Exit**: Esc at picker leaves.

## /peer-name
- **Entry point**: `/peer-name`
- **Interactive steps**:
  1. Prompts for new session name (type in the modal, press Enter).
  2. Enter name → sets alias.
- **Direct usage**: `/peer-name <name>` sets immediately.
- **Completion**: exits after setting.
- **Exit**: Esc at prompt cancels.

## /peer-request
- **Entry point**: `/peer-request`
- **Interactive steps**:
  1. Picker lists actions: Create, Status, Respond, Cancel.
  2. Select an action → prompts for required fields.
  3. **Create**: prompts for `<agent_id> <summary>` → creates.
  4. **Status**: prompts for `<request_id>` → shows status.
  5. **Respond**: prompts for `<request_id> <action>` → responds.
  6. **Cancel**: prompts for `<request_id>` → cancels.
- **Nested**: none.
- **Completion**: returns to chat after each.
- **Exit**: Esc at action picker leaves.

## Usage records
Every slash-command invocation is appended to `<runtime_root>/command-usage.jsonl`
(one JSON object per line: timestamp, command, args, session_id, outcome).
View the recent records with:
```
hermes peer usage --limit 10
```

## General behavior
- All commands accept direct arguments for power users (e.g. `/peer-broadcast g1 hello`).
- When arguments are missing or the command is called bare, the interactive picker opens.
- The host owns all I/O: curses picker for choices, a free-text modal (`_prompt_free_text_modal`)
  for typed input. The modal shows a visible panel: "Type your input below, then press Enter.
  ESC or Ctrl+C to cancel."
- Plugins supply purely declarative specs: `{title, items, actions, children, prompt, empty}`.
- Actions are handlers `(value, text=None) → str|spec`; the host renders strings or recurses into specs.
- Esc pops one level; Esc at the root exits cleanly.
- Commands are one-shot: after an action completes you return to chat (see Completion model above).