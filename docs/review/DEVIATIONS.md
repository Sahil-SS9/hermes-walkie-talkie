# Deviations and known limitations — v0.1.0-rc1

Every deviation from the plan/brief is recorded here with its rationale.
Nothing here is hidden; anything marked unverified stays unverified.

## Plan deviations

1. **macOS execution not performed.** CI workflows for macOS are configured
   (Linux + macOS × Python 3.11–3.13) but no remote CI run was executed
   during the goal. The plan explicitly defers this to post-goal approved
   remote CI; nothing claims macOS execution occurred.
2. **`hermes plugins install <local-path>` unsupported.** This Hermes version
   only accepts Git URLs / owner-repo identifiers; a `file://` install
   produced a partial copy (CLI quirk). AP-207 instead verified the
   clone-style layout (what a GitHub install produces) and the wheel entry
   point in disposable homes. E2E-909/910 use the clone-style layout.
3. **Full Hermes suite runs with pre-existing baseline failures.** The
   baseline commit (3f812796bb) itself has collection errors and failures
   (e.g. `gateway/stream_consumer.py` missing `import re`; tests referencing
   `build_auto_tts_output_path` / `_HYGIENE_COOLDOWN_LADDER_MULTIPLIERS`
   that do not exist at that commit). Verified identical on the pristine
   base worktree. The gate is ZERO candidate-only failures versus the exact
   base; the candidate does not fix unrelated baseline defects (out of
   scope).
4. **Canonical checkout HEAD drifted externally.** During the goal the
   canonical `/home/kensei/repos/KenseiAgent` HEAD moved to 54175436a0 by
   environment activity, not by this goal. The candidate worktree pins its
   own branch/HEAD; a detached baseline worktree at the original base
   (3f812796bb) was created for the rigorous comparison.
5. **E2E-910 model-free delivery.** Two real Hermes-binary sessions under
   disposable homes exchange a message through the installed plugin without
   a model call (no credentials exist for a live turn). Host-seam wake
   behaviour is proven at the P1 seam level; a live model turn remains a
   post-goal pilot step requiring credentials.
6. **Cross-UID Linux validation skipped locally.** The deterministic
   same-UID tests pass; the chown-based wrong-owner tests skip when the
   environment cannot chown (non-root). Real cross-UID validation is
   deferred to approved CI, as recorded in the ledger.
7. **Receiver-side queue semantics.** On the CLI, injected text lands in a
   dedicated conversational queue drained before user input; it is never
   treated as a slash command or shell line. Busy-gateway injection queues
   in the session FIFO. Both are covered by tests; the gateway surface
   supports `mode="queue"` only in v1 (steer/interrupt return False there).

## Known limitations (v1)

- Same-machine, same-OS-user only. No cross-machine transport, no
  encryption in transit (not needed for the local boundary), no
  authentication beyond the OS-user boundary.
- Windows named pipes: out of scope. macOS runtime behaviour: unverified.
- No broadcasts/groups/team orchestration; no file transfer; no remote
  execution; no MCP transport (future adapter possible).
- Explicit agent action is required for replies — no automatic ping-pong.
- The upstream Hermes seam is a local candidate; until merged upstream, the
  plugin requires the candidate core (or a later build with the seam).

## Deviations in the Hermes core candidate

- The inert-control guarantee uses a new `MessageEvent.non_control` flag
  (set only by the plugin injection path) rather than gating on the
  pre-existing `internal` flag — the latter would have changed behaviour
  for handoff/goal/background internal events. This matches the upstream
  PR #64436 "non-control input" direction and is documented in the commit.
