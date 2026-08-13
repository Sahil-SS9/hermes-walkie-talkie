# ADR-0006: Hermes Desktop plugin boundary

- Status: Accepted (11 August 2026)
- Plan: Hermes Walkie Talkie V1.1+ §3.6, G6, P8

## Context

V1.1 must expose peers, groups, broadcasts, inbox, requests and health in the
Hermes Desktop app without adding peer-specific feature logic to Hermes core
(NG-07, NG-08) and without reading SQLite/registry files directly from the
renderer (G6.6).

## Decision

### Backend ownership

- Python plugin backend: `dashboard/manifest.json` + `dashboard/plugin_api.py`
  in the standalone repo, namespaced at `/api/plugins/hermes-peer/...`
  (G6.3), mounted by the core dashboard plugin system with session-token auth
  (verified in core `hermes_cli/web_server.py` — every `/api/plugins/...`
  route passes `auth_middleware`; WebSocket requires `?token=`).
- Backend owns shared truth; renderer state is a profile/connection-scoped
  cache, cleared/reconciled on switches (G6.8).

### Desktop surface

- Disk plugin: `<local HERMES_HOME>/desktop-plugins/hermes-peer/plugin.js`
  (G6.2) loaded by the core `loadRuntimePlugin` contract (verified:
  `apps/desktop/src/contrib/runtime-loader.ts` — disk door, integrity check,
  bare-specifier rewrite for `@hermes/plugin-sdk`/`react*`, dispose-before-
  reload, error isolation).
- UI uses plugin `ctx.rest` and `ctx.socket` only (G6.6). WebSocket events
  accelerate updates; polling remains the authoritative fallback, including
  OAuth/remote modes where plugin sockets may be unavailable (G6.7).
- Panel + status-bar contributions use `@hermes/plugin-sdk`, React, and
  existing design primitives (G6.4, G6.5).
- No peer feature module under core `apps/desktop/src/plugins/` (G6.2,
  NG-07). Core changes only: generic `session.create`/`session.resume`
  lifecycle platform accuracy (`source='desktop'` label, P8 core file).

### Release posture

- Plugin is opt-in/installable, cleanly unloadable, never auto-installed
  (G6.9, P7.7). Build checked `plugin.js` into the wheel/sdist (P8.11,
  ACC-17). No live activation during this goal (G6.9, P8.12, ACC-22).

## Consequences

- Standalone repo grows `dashboard/`, `desktop/`, `hermes_peer/assets/desktop/`.
- Core changes are strictly the generic lifecycle label fix plus tests; the
  desktop runtime contract is treated as fixed (G6.1).
- Desktop E2E on Linux is runnable; native Windows desktop E2E shares the
  Windows-native blocker of ADR-0005.
