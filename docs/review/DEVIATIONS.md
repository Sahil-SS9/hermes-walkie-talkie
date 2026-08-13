# Deviations and known limitations — V1.1

This file records actual remaining limits. Historic statements that remote CI
had not run are superseded by PR #1 evidence.

## Evidence status

1. **Native Windows transport and ACL evidence is complete.** GitHub Actions
   run `31723046182` executed the `native-windows` job on `windows-latest` and
   passed named-pipe, SID/DACL and real multi-process exchange gates.
2. **macOS CI is complete.** Python 3.11–3.13 and the Desktop build jobs passed
   in the same PR matrix.
3. **Windows wheel-install and full Desktop/Electron interaction are not yet
   covered.** They are explicit follow-up coverage, not claims made by the
   current native transport job.
4. **Live host activation remains conditional.** Walkie Talkie uses Hermes'
   public queued injection seam. The upstream queue/steer/interrupt work is
   tracked separately in NousResearch/hermes-agent PR #85279.

## Known limitations

- Same-machine, same-OS-user only: no cross-machine transport, file transfer
  or remote execution.
- Groups are flat: no nesting.
- Cancellation is advisory: it does not interrupt an active model/tool turn.
- Metrics and events are content-free: no message bodies, prompts, credentials
  or outbound telemetry.
- The Desktop bundle is built and tested in CI, but a real Hermes
  Desktop/Electron interaction run on Windows is not yet recorded.

## Not implied by merge

A PR merge does not publish a package, install the plugin, enable it in a
Hermes profile or activate the Desktop bundle. Those are explicit later
operator actions.
