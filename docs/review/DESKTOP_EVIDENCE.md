# Desktop plugin evidence

## What ships

The wheel (`dist/*.whl`) and the git tree contain the compiled Desktop
bundle under `hermes_peer/assets/desktop/`:

- `plugin.js` — vite build of `desktop/src/` (React + TypeScript),
  single ESM file, externalizes `@hermes/plugin-sdk` and `react*`
  per the core loader contract.
- `style.css` — panel styles.

`dashboard/manifest.json` declares the namespaced
`/plugins/hermes-peer` tab; `dashboard/plugin_api.py` serves the
FastAPI router at `/api/plugins/hermes-peer/`.

## Verified on Linux (real evidence)

- `desktop/`: `npm run typecheck` clean, `npm test` 7/7 vitest passed,
  `npm run build` produced `dist/plugin.js` (7.63 kB) + `style.css`.
- `scripts/verify_wheel_assets.py`: wheel ships all 8 required paths
  (Python packages, py.typed, dashboard manifest, desktop assets).
- Wheel-install smoke (P10.5 Linux leg): installed into a disposable
  venv, `hermes peer desktop install --home <tmp>` copied the bundle,
  plugin imports, config loads.
- `tests/e2e/test_desktop_plugin_install.py` — install roundtrip.
- `tests/e2e/test_desktop_surface.py` — a real process opens a desktop
  session; a second real process observes it with `surface=desktop`
  (locks the `_surface_of("desktop") → "desktop"` mapping).
- `tests/unit/test_dashboard_api.py` — 13 API tests incl. 503/404
  branches, WS upgrade/unauthorized close.
- `tests/security/test_desktop_no_auto_install.py` — wheel ships assets
  but installation is explicit-only (G6.9); plugin load never
  auto-installs.
- `tests/unit/test_desktop_install_edges.py` — missing bundle raises,
  missing style.css tolerated, absent remove/status.

## Boundaries enforced

- No auto-install: `install_desktop_plugin()` is only called by the
  explicit `hermes peer desktop install` command (G6.9).
- The plugin is never activated in a live app by this command (P8.12).
- The WebSocket `/events` channel delegates auth to the dashboard's
  canonical `_ws_auth_ok` gate (G6.7); polling remains the fallback.
- Metrics/API responses carry no message content (G1.2/G1.3).

## NOT verified

- Live activation inside Hermes Desktop with the real plugin host
  (requires a desktop app session; out of scope on this rig).
- Windows/Electron desktop E2E (`P9.4`) — native Windows evidence is
  BLOCKED (see WINDOWS_EVIDENCE.md).
