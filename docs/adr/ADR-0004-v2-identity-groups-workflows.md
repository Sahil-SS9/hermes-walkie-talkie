# ADR-0004: V2 identity, protocol, groups and workflows

- Status: Accepted (11 August 2026)
- Supersedes: ADR-0003 (extended, not replaced)
- Plan: Hermes Walkie Talkie V1.1+ §3.1, §3.4, G2, G3, G4

## Context

V1 (`agent-peer/1`) provides session-scoped peer identity, queue-only busy
delivery, inert-control dispatch and a point-to-point envelope. V1.1 needs
long-lived identity across session rotation, persistent groups, broadcasts and
structured request/reply workflows without weakening any V1 safety contract
(NG-15).

## Decision

### Two-level identity

```text
agent_id    = stable adapter/profile identity, persisted across sessions
peer_id     = immutable live-session registration identity (V1 semantics)
instance_id = process/listener incarnation fence
```

- `peer_id` remains exactly the V1 identity: immutable for one live session
  registration (G2.1).
- `agent_id` is added as a long-lived identity supplied by the adapter. For the
  Hermes adapter it is persisted inside that profile's `HERMES_HOME`
  (G2.3), owner-only, never inferred from mutable alias/path text (G2.3,
  G3.3).
- A group stores `agent_id` only. Resolution to a live `peer_id` is explicit
  and fail-closed (G2.5). Alias/profile-name/filesystem-path are presentation
  metadata, never membership authority (NG — G3.3).
- Adapters that do not supply `agent_id` remain V1-only peers: listable,
  simple-message capable, group/workflow operations return `incompatible`.

### Deterministic routing (G2.5)

Resolution order for an agent target:

1. pinned live `peer_id` (exact match) → that session
2. else exactly one explicitly primary session → that session
3. else exactly one live session → that session
4. else → fail `ambiguous`, no delivery

Never silently send to every session in a profile (G2.6).

### Protocol evolution (G3.4)

- Preserve `agent-peer/1` point-to-point interoperability byte-for-byte.
- Add `agent-peer/2` for capabilities, stable identity, groups and structured
  workflows.
- Discovery records advertise supported protocols and capabilities.
- Negotiation picks the highest mutual version.
- V2 discriminated kinds (strictly validated bounded JSON, unknown/oversized
  rejected before persistence or delivery):
  - `message`, `receipt`, `request`, `request_status`, `request_cancel`,
    `discover`, `alive`
- V1 peers receiving group/workflow operations return `incompatible`; never
  degrade into free text.

### Broadcast semantics (G3.5)

A broadcast is an orchestrator over ordinary point-to-point sends. Parent
persisted before fan-out; child IDs deterministic from
`(broadcast_id, recipient agent_id, resolved peer_id)`; bounded concurrent
sends; parent retry idempotent (G3.7).

### Workflow semantics (G4)

- Typed `request`, `response/progress`, `cancellation` payloads; `reply_to`
  is not overloaded into a fake state machine (G4.1).
- Persisted state machine:
  `created → queued → accepted → in_progress → completed|failed|refused|cancelled|expired`
- Transport receipt ≠ workflow completion (G4.4).
- Cancellation advisory only — never interrupts an active protected tool, never
  grants command authority (G4.6, G4.9).
- Requests are conversational input only (`<peer_request>`), inert (P5.6).

## Consequences

- Two migration waves in the owner-local SQLite store, both idempotent and
  copy-on-test (P3.6, P4.1, P5.2).
- `ambiguous`/`incompatible` are new result states; V1 state meanings unchanged.
- All existing V1 tests remain green (ACC-04, ACC-08).
