# AP-007 — Architecture validation record (P0 gate)

Executor: single agent, one Hermes session. Date: 9 August 2026.

## Validation performed

The three ADRs were checked against (a) the source brief, (b) the current
Hermes code at `3f812796bb` (canonical KenseiAgent HEAD) and (c) the
upstream references refreshed on 9 August 2026.

### Upstream refresh (AP-001) — result

| Reference | State | Notes |
|---|---|---|
| NousResearch/hermes-agent#81885 | open | Local cross-session messaging (intercom) proposal — compatible with this design |
| #64436 | open | Plugin injection into existing gateway sessions; per-plugin gate + stored-route reuse — reconciled into ADR-0002 |
| #70406 | open | Owner-local IPC into exact live gateway session — same direction, not merged; our seam is plugin-scoped |
| #80920 | open | `tui_gateway.server.inject_external_message` dashboard routing — adopted as the TUI host entry point |

None merged → the isolated worktree carries a reconciled local
implementation of the same public shape; no incompatible route created.

### Check results

1. ADR-0001 vs brief §"Session Registration"/"A good default architecture":
   the brief's `$HERMES_HOME/peer-messaging` layout is explicitly proposed
   "only as a proposed structure. Change it if research identifies a better
   Hermes-native solution." Cross-profile and cross-worktree discovery
   (brief §Worktree Acceptance Test) is impossible under a per-`HERMES_HOME`
   root, so the plan's shared owner-local roots (`$XDG_RUNTIME_DIR/agent-peer`,
   `${XDG_STATE_HOME:-~/.local/state}/agent-peer`) are adopted. **Deviation
   from the brief's example layout, justified by the brief itself.**
2. ADR-0002 vs `hermes_cli/plugins.py:505` (`inject_message` CLI-only,
   private fields, busy-interrupt): extended additively; Boolean preserved;
   gateway/TUI routes host-owned; per-plugin `allow_gateway_injection` gate.
   **No ambiguity remains about busy-delivery semantics: queue never touches
   `_interrupt_queue`.**
3. ADR-0003 vs brief §"Message Envelope"/"Delivery Acknowledgements":
   field names follow the plan §4.3 (authoritative): `message_id`,
   `created_at`, `expires_at`, `sender`, `recipient_peer_id`, `reply_to`,
   `conversation_id`, `hop_count`, `kind`. Receipt set is the plan's:
   `queued|held|refused|unreachable|expired|invalid|rate_limited|over_capacity`.
   Transport ack ≠ agent completion, as the brief requires.

### Assumptions recorded

- Linux is release-blocking; macOS CI configured but not executed; Windows
  out of scope (plan §2).
- The Hermes core change is limited to the generic delivery seam; no
  peer-specific code in core (ADR-0001).
- `hermes_peer` will feature-detect the seam and fail clearly if absent
  (AP-006) — private-field fallback banned.

## Gate P0 verdict

All three ADRs recorded and internally validated; no unresolved
session-targeting or busy-delivery ambiguity. **Gate P0 PASSED.**
