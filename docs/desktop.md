# Hermes Desktop plugin

## What ships

The wheel contains the compiled Desktop bundle:

- `hermes_peer/assets/desktop/plugin.js` — vite build of `desktop/src/`
  (React + TypeScript), single ESM file
- `hermes_peer/assets/desktop/style.css` — panel styles

The `dashboard/` package ships the plugin host backend:

- `dashboard/manifest.json` — plugin manifest (tab `Hermes Peer`)
- `dashboard/plugin_api.py` — FastAPI router mounted by the Hermes Desktop
  host at `/api/plugins/hermes-peer/`

## Install (explicit only, G6.9)

```sh
hermes peer desktop install    # copy the compiled bundle into HERMES_HOME/desktop-plugins/hermes-peer/
hermes peer desktop status     # installed? version? paths?
hermes peer desktop remove     # remove the installed copy
```

Installing is **never automatic**: plugin load does not write to
HERMES_HOME (`tests/security/test_desktop_no_auto_install.py`). The
Desktop host discovers installed plugins from the plugins door; only an
explicit install makes this plugin appear.

## Dashboard API

| Route | Returns |
|---|---|
| `GET /health` | doctor snapshot + remedies |
| `GET /metrics` | content-free metrics (counts/latency/failure-reason/held-depth/stale-events) |
| `GET /peers` | live peers with surface/profile/status |
| `GET /groups` | groups + members |
| `GET /broadcasts` | broadcast outcomes per recipient |
| `GET /inbox` | this profile's received messages |
| `GET/POST /requests` | request list / create |
| `POST /requests/{id}/respond` | recipient transitions |
| `WS /events` | event stream (dashboard auth gate + always-frame heartbeat) |

The WebSocket delegates upgrade auth to the dashboard's canonical
`_ws_auth_ok` gate; the server always sends a frame (heartbeat or events)
so clients never hang on an empty tail.

## Panel

`PeerPanel` shows five tabs — Peers, Groups, Inbox, Requests, Health —
over a profile-scoped cache (`desktop/src/store.ts`): switching profiles
clears the cache so another profile's state never leaks into view. The
panel contributes a status-bar item and a right-column pane via the host's
`register` API.

## Build

```sh
cd desktop
npm ci
npm run typecheck && npm run lint && npm test
npm run build          # dist/plugin.js + dist/style.css
# copy into the package asset:
cp dist/plugin.js ../hermes_peer/assets/desktop/plugin.js
cp dist/style.css ../hermes_peer/assets/desktop/style.css
```

`@hermes/plugin-sdk` is externalized and loader-injected at runtime; a
local type stub (`desktop/src/sdk-stub.d.ts`) mirrors the consumed
PluginContext surface for standalone typecheck.

## Verification

- `scripts/verify_wheel_assets.py` asserts the wheel carries the dashboard
  + assets (CI step).
- `tests/e2e/test_desktop_surface.py` proves a real process opens a
  desktop-surface session and a second real process observes the peer with
  `surface=desktop`.
- `tests/unit/test_dashboard_api.py` exercises the API router with a bare
  TestClient against a stubbed process-local manager.
