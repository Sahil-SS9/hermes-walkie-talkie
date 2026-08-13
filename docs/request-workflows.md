# Structured request/workflows (G4)

## State machine

A pure decision table (`agent_peer/workflows.py`) drives requests:

```
created → queued → accepted → in_progress → completed
                                      ↘ failed | refused | cancelled | expired
```

- Every transition is validated against the decision table; impossible,
  stale or out-of-order transitions raise `InvalidTransition`.
- `cancel` is advisory from every non-terminal state (no interrupt seam).
- Terminal states (`completed`, `failed`, `refused`, `cancelled`,
  `expired`) are frozen.

## Aggregate

`agent_peer/request_models.py` Request aggregate fields:

- `request_id` — unique id
- `sender_agent_id`, `recipient_agent_id` — stable agent ids
- `state`
- `deadline` — expiry check on read
- `idempotency_key` — `(sender, key)` dedup returns the original request
- `correlation_id` — cross-request correlation
- `parent_request_id` — optional parent link
- `payload` — summary + optional structured body

`RequestStore` keeps `requests` + `request_events` (ordered event log) in
SQLite (schema v4). Empty idempotency keys are stored as NULL so keyless
requests coexist under SQLite's UNIQUE semantics.

## Tools

| Tool | Purpose |
|---|---|
| `peer_request_create` | create a request to a recipient `agent_id`; returns `request_id` + delivered receipt |
| `peer_request_status` | read current state + event log |
| `peer_request_respond` | recipient-only: `accept` / `progress` / `complete` / `fail` / `refuse` |
| `peer_request_cancel` | advisory cancel from a non-terminal state |

Recipient-only guard: a request can only be transitioned by its
recipient; the sender may cancel or read status.

## Inert conversational boundary

The recipient's host receives the request as an inert `<peer_request>`
marker — plain conversational text inside an untrusted boundary, never a
host command. There is no interrupt seam and no command authority granted
(`tests/security/test_request_inert_control.py`).

## Real-process evidence

`tests/e2e/test_structured_request_reply.py` drives two real Hermes
processes: A creates a request addressed to B's stable agent_id; B's host
receives the inert boundary and completes queued → accepted → progress →
completed through the real tool pipeline. `tests/e2e/test_real_broadcast.py`
exercises group + broadcast on the same harness.
