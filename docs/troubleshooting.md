# Troubleshooting

`hermes peer doctor` is the first stop:

```bash
hermes peer doctor
```

It reports the delivery-seam status, the runtime directory, registry entry
count, local sessions and the current inbound policy, and exits non-zero
when something is wrong.

## Missing delivery seam

**Symptom:** the plugin loads but logs
`host Hermes lacks the additive inject_message seam (mode/target_session)`.

**Cause:** the host Hermes build predates the additive `inject_message`
seam (mode/target_session parameters). Delivery is disabled by design; no
private-field fallback exists.

**Fix:** run Hermes from the candidate core worktree
(`/home/kensei/worktrees/hermes-walkie-talkie-core`, branch
`candidate/hermes-walkie-talkie-p1-20260809`) or a later build with the
seam. See `docs/compatibility.md` for the minimum requirement.

## Unsafe runtime paths

**Symptom:** `ConfigurationError: runtime dir must be owner-only ...` or
`runtime parent must be owner-only ...`.

**Cause:** `$XDG_RUNTIME_DIR` (or the fallback state dir) exists with
group/world permissions, is a symlink, or belongs to another user.

**Fix:** fix the directory mode/ownership (`chmod 0700`, `chown` to your
user) or point `XDG_RUNTIME_DIR` at a secure path. The plugin never repairs
or uses insecure paths.

## Stale peers / crashed sessions

**Symptom:** a peer that crashed still appears in discovery, or a new
session cannot bind its socket.

**Behaviour (by design):** a crashed peer's registry entry is removed only
after the stale threshold (45 s) **and** a failed socket handshake. A new
process reclaims a stale socket only when nothing listens on it.

**Fix:** wait for the stale threshold, or remove the entry manually only if
you are certain the process is dead:
`rm ~/.local/state/agent-peer/runtime/registry/<peer_id>.json`.

## Peers do not see each other

Check:

1. Both processes run as the same OS user.
2. `XDG_RUNTIME_DIR` is either unset or a secure owner-only directory, and
   is the same for both (or both fall back to the same state root).
3. `hermes peer doctor` reports a healthy runtime dir on each side.
4. No leftover `/tmp/agent-peer-<uid>` sockets from killed processes block
   the reclaimed path (they self-heal on next registration).

## Socket path too long

**Symptom:** `OSError: AF_UNIX path too long` in an unusual environment.

**Design:** sockets live in a short `s/` directory with hash-shortened names,
and relocate to `/tmp/agent-peer-<uid>` when the runtime root is too deep.
If you still hit the bound, your `/tmp` itself is exceptionally deep — set
`AGENT_PEER_RUNTIME_DIR` to a short secure path.

## Unsupported platforms

- **Linux**: release-blocking, fully verified.
- **macOS**: CI configured; runtime execution pending approved remote CI.
- **Windows**: out of scope for v1 (no named-pipe transport).

## Persistent state

Messages live in `~/.local/state/agent-peer/messages.sqlite3`. Uninstalling
the plugin never deletes it automatically; remove it explicitly if you want
a clean slate (after checking nothing else references it).
