# Groups and broadcasts

## Groups (G3)

Persistent groups live in SQLite (schema v3). A group is owned by the
profile that created it and has:

- a **name** unique under case-insensitive normalisation (owner-scoped)
- an **owner** (stable `agent_id`)
- **members** addressed by stable `agent_id` (aliases are display-only —
  membership is never keyed on an alias)
- a **member cap** (default 32, hard ceiling 128)
- an **optimistic revision** for concurrent mutation detection

### Operations

| Command | Behaviour |
|---|---|
| `peer_group_manage action=create name=X` | creates a group, returns `group_id` |
| `peer_group_manage action=add_member group_id=G member_agent_id=A` | adds member A |
| `peer_group_manage action=remove_member group_id=G member_agent_id=A` | removes member A |
| `peer_group_manage action=delete group_id=G` | owner-only delete |
| `peer_group_list` | lists groups with member counts |

Rules: only the owner may delete; only the owner may mutate members (the
store enforces the owner fence); unknown/foreign groups fail closed; caps
are enforced before any write.

## Broadcasts (G3)

`BroadcastEngine` fans one message out to every member of a group:

- **Parent-first persist**: the broadcast row is written before any child.
- **Deterministic child IDs**: `child_id = f(broadcast_id, agent_id,
  peer_id)` so the same logical child is addressable from any sender.
- **Atomic single-writer gate**: a child transitions `created →
  in_flight` atomically; only one concurrent duplicate broadcaster wins the
  gate, the losers read the recorded outcome (no duplicate injection).
- **Bounded concurrency**: fan-out respects the configured ceiling
  (default ≤ 8 concurrent, hard ≤ 64).
- **Explicit partial results**: per-recipient state — `queued` (accepted by
  the host queue), `held` (delivered to a busy/mid-turn session — queue-only,
  never an interrupt), `skipped` (sender excluded), `unreachable` (no live
  session).
- **Sender self-exclusion**: the sender never receives its own broadcast.

### Summary shape

```
{
  "broadcast_id": "...",
  "total": N,
  "queued": M,
  "held": K,
  "skipped": S,
  "unreachable": U,
  "failures": {"count": F, "items": [...]}
}
```

`queued + held` are the delivered states; `held` is surfaced explicitly
(P9.5) and is NOT a failure.

## Delivery semantics (busy targets)

- Idle target → the host starts a new turn (`inject mode="queue"`).
- Busy target (mid-tool-turn) → the message is queued at the safe boundary
  or stored HELD; the active tool is never interrupted (`mode="queue"`
  never touches the interrupt queue). See `tests/security/
  test_busy_target_queue_only.py` and the real broadcast E2E
  (`tests/e2e/test_real_broadcast.py`).

## Real-process evidence

`tests/e2e/test_real_broadcast.py` drives two real Hermes processes
through the real deferred tool pipeline: create group → add member by
stable agent_id → broadcast; the child reaches the recipient's store over
the real local transport. The group_id is created at runtime by the tool
and threaded through the same deferred dispatch via a callable fake-model
script (`fake_model_server.py` `script_fn`).
