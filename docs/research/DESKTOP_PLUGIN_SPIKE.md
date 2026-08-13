# Desktop Disk-Plugin Spike Report (P0.8)

- Date: 11 August 2026
- Plan: Hermes Walkie Talkie V1.1+ P0.8
- Spike location (disposable, quarantined): `/tmp/wtt-spike/desktop-plugin-spike/plugin.js`

## Purpose

Prove the Hermes Desktop disk-plugin loader contract before production code:
loader, `ctx.rest`, `ctx.socket`, profile scoping, unload and polling fallback
(plan G6.2, G6.6, G6.7, G6.9).

## Contract verified from core source (direct evidence)

Core worktree: `/home/kensei/worktrees/hermes-walkie-talkie-core-v1-1` @
`2a853f8681e5aecd8b7059272598c33c17bf9370` (clean V1 draft-PR head).

- `apps/desktop/src/contrib/runtime-loader.ts` — the `loadRuntimePlugin`
  pipeline: plain ESM source → integrity check → bare-specifier rewrite
  (`@hermes/plugin-sdk`, `react*` → live shim blob URLs) → blob `import()` →
  validate default `HermesPlugin` → register(ctx).
- Disk door: `<local HERMES_HOME>/desktop-plugins/<name>/plugin.js`, resolved
  via Electron `desktopPluginsRoot()`; the backend's remote `hermes_home` must
  NEVER feed the local plugin scan (regression guard #66899, covered by
  `runtime-loader.test.ts` `scanDiskPlugins`).
- Same-id reload disposes previous registrations first; failures toast+log;
  a broken plugin cannot take the app down (error isolation, not a capability
  boundary — documented in the loader's security comment).
- `ctx` provides `rest`, `socket`, `storage`, `navigate`, `host.request`,
  `notify`, i18n, status-bar and panel contributions.
- Dashboard plugin backend contract (for P8 `dashboard/`): FastAPI router in
  `dashboard/plugin_api.py`, mounted at `/api/plugins/<name>/`, session-token
  auth via `hermes_cli.web_server.auth_middleware`; WebSocket `/events` uses
  `?token=` (verified from `plugins/kanban/dashboard/plugin_api.py`).

## Spike result

```text
$ node --check plugin.js
SYNTAX OK
$ node contract-check
PASS imports @hermes/plugin-sdk
PASS imports react
PASS default export createPlugin
PASS plugin id hermes-peer
PASS activate(ctx) present
PASS ctx.rest only (no sqlite/fs)
PASS disposers returned
PASS socket fallback
```

The spike plugin is plain ESM (compiled-output shape), uses only `ctx.rest` +
`ctx.socket` for backend reads (no SQLite/registry), returns a full disposer
array for clean unload, and treats polling as the authoritative fallback when
the socket is unavailable.

## Native Electron gate (P8/P9)

The real Electron load/unload, profile scoping and switch-reset behaviour are
proven in P8 (`apps/desktop/src/contrib/runtime-loader.test.ts` in core) and
P9.3/P9.4 with a real Desktop surface. On Linux, the core runtime-loader unit
suite covers the loader contract; native Windows desktop E2E shares the
Windows-native blocker of ADR-0005.

## Conclusion

- Loader contract shape: proven against core source + spike checks.
- Production plugin.js build: P8.
- Native Electron/Windows surface: P8/P9 gates (Windows native blocked until
  runner exists).
