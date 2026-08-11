# Deviations and known limitations — V1.1+

Every deviation from the plan is recorded here with its rationale.
Nothing here is hidden; anything marked unverified stays unverified.

## Plan deviations

1. **Native Windows release evidence BLOCKED (never COMPLETE).** Per the
   plan's remote-CI approval gate and ADR-0005, the Windows named-pipe
   backend is implemented (fail-closed SID/DACL) but native proof —
   `windows-latest` CI, real named-pipe connect/deny/teardown, Windows
   wheel install, Desktop-on-Windows E2E — has not been executed on this
   rig. The deterministic verifier hard-fails this check on non-win32.
   Status: `IMPLEMENTED — WINDOWS RELEASE EVIDENCE BLOCKED`.

2. **Remote CI not started.** `.github/workflows/ci.yml` (ubuntu/macos/
   windows × py3.11–3.13) and the desktop build workflow are prepared
   but not pushed or run. Pushing is gated on Sahil's explicit approval
   (plan approval gate). macOS execution also deferred for this reason.

3. **macOS execution not performed.** Same remote-CI gate; macOS-specific
   peer-credential paths are covered by unit tests but not executed on a
   real macOS runner.

4. **P10.5 Windows wheel-install leg not run.** The Linux leg ran clean
   (disposable venv + doctor + desktop install). The Windows leg stays
   unticked pending a Windows runner.

5. **Plan checkboxes ticked post-hoc.** All 109 plan sub-goals are now
   ticked where genuinely complete (101), with 8 deliberately left
   unticked (P9.2/P9.4/P9.9 Windows evidence, P10.5 Windows leg, and
   P11.9–P11.12 review-packet/independent-review steps still in flight).
   The ticker script records what was done; the deterministic verifier
   independently validates reality and accepts only the documented
   blocked/pending set as unchecked.

## Known limitations (V1.1)

- Groups are flat (no nesting); cancellation is advisory (no interrupt
  seam).
- Cross-machine transport, file transfer and remote execution are out of
  scope.
- Metrics/events are content-free by design (G1.2/G1.3) — no message
  bodies, prompts, credentials or outbound telemetry.
- Desktop live activation inside Hermes Desktop with the real plugin
  host was not exercised on this rig (requires a desktop app session).

## Things explicitly NOT claimed

- No Windows-native security evidence is claimed.
- No macOS execution is claimed.
- No remote CI run is claimed.
- No live Desktop activation is claimed.
- Nothing was pushed, merged, published, tagged, installed or activated.
