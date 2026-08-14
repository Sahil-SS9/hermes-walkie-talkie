# Dashboard Plugin — Setup & Operations

How to install, enable, operate, and uninstall the Walkie-Talkie Dashboard
plugin. This plugin uses the **public Hermes Dashboard Plugin API only** —
no private internals, no core patches.

## Prerequisites

- **Hermes Agent** with dashboard support (the `hermes dashboard` command).
  The dashboard ships with Hermes; no separate install.
- **Node.js 22+** (only needed if you rebuild the frontend bundle from
  source; the wheel ships a pre-built `dist/`).
- **Walkie-Talkie plugin installed** — the dashboard tab is part of the
  Walkie-Talkie plugin package. Install the plugin first (see the main
  [README](../README.md) quick-start).

## Package & build assets

The dashboard frontend is a compiled ES module bundle:

```
dashboard/
├── manifest.json       # name, label, icon, version, tab config, entry/css/api
├── dist/
│   ├── index.js        # compiled React bundle (ES module)
│   ├── style.css       # compiled stylesheet
│   └── build-meta.json # build timestamp + checksums
├── plugin_api.py       # FastAPI router mounted at /api/plugins/hermes-peer/
├── src/                # TypeScript source (not shipped in wheel)
├── tests/              # Node.js test suite (not shipped in wheel)
└── package.json        # npm metadata (not shipped in wheel)
```

The wheel (`hermes_walkie_talkie-*.whl`) includes `dashboard/dist/` and
`dashboard/plugin_api.py`. Source files and `node_modules` are excluded.

## Install

### From a local checkout

```bash
hermes plugins install /path/to/hermes-walkie-talkie
```

This copies the plugin into `~/.hermes/hermes-agent/plugins/hermes-peer/`.
The dashboard auto-discovers `dashboard/manifest.json` inside the plugin
directory.

### From a wheel (pip)

```bash
pip install hermes-walkie-talkie
```

The wheel places the plugin under the Hermes plugins directory. After
install, Hermes must rescan:

```bash
hermes plugins list          # verify hermes-peer appears
```

## Enable & rescan

Plugins installed from a local path are enabled by default. If the plugin
shows as disabled:

```bash
hermes plugins enable hermes-peer
```

The dashboard rescans plugins on startup. If the dashboard is already
running, restart it:

```bash
hermes dashboard --stop
hermes dashboard --host 0.0.0.0 --insecure --tui --no-open --skip-build
```

After restart, the **Walkie-Talkie** tab appears in the dashboard sidebar
at the route:

```
/plugins/hermes-peer
```

## How API auth works

The plugin frontend uses the host's public SDK globals:

- `window.__HERMES_PLUGIN_SDK__.fetchJSON(url)` — authenticated REST calls.
  Handles both loopback (session-token header) and gated OAuth (cookie)
  modes transparently.
- `window.__HERMES_PLUGIN_SDK__.buildWsUrl(path)` — builds an authenticated
  WebSocket URL for real-time peer events. In gated mode this mints a
  single-use ticket; in loopback mode it appends the session token.

The plugin never reads `window.__HERMES_SESSION_TOKEN__` directly and never
assembles auth headers by hand. All API calls go through the host SDK.

The backend (`plugin_api.py`) is a FastAPI router auto-mounted by the
dashboard at `/api/plugins/hermes-peer/`. It reads from the Walkie-Talkie
registry (the same one the CLI tools use) — no separate database, no
duplicate state.

## Supported UX

| Feature | Status | Notes |
|---------|--------|-------|
| Live peer list | ✅ | Rail + table view, auto-refresh via WebSocket |
| Peer inspector | ✅ | Hover popover with agent ID, surface, status, profile, CWD |
| Copy agent ID | ✅ | Clipboard API with success/failure feedback |
| Focus peer detail | ✅ | Full detail surface, survives tab changes |
| Groups | ✅ | Create, list, view members |
| Inbox | ✅ | Message list with receipt detail modal |
| Requests | ✅ | Structured request list with detail modal |
| Health | ✅ | Backend, live peers, pending/held counts, problems |
| Theme persistence | ✅ | 8 themes (Ember Relay + 7 local), persisted in `localStorage` |
| Speech-to-text | ⚠️ | UI present with explicit "unavailable" fallback; no live STT |
| Control Room | ⚠️ | Attention banner only (held/pending counts); no deep-link actions |

### Theme persistence

The selected theme is stored in `localStorage` under the key
`wt-dashboard-theme`. It survives tab switches, page reloads, and dashboard
restarts. The default is **Ember Relay**.

### STT limitation

The speech-to-text panel renders a "Speech-to-text unavailable" message.
The plugin does not bundle or invoke any STT provider. This is intentional:
the dashboard host's STT integration is not exposed through the public
plugin SDK.

### Control Room limitation

The Control Room banner shows aggregate counts of held inbox messages and
pending requests. It does not provide deep-link navigation to individual
items. This is a deliberate scope boundary — the Control Room is an
attention surface, not a full action centre.

## Troubleshooting

### Verify the plugin is installed

```bash
hermes plugins list | grep hermes-peer
```

Expected output includes `hermes-peer` with status `enabled`.

### Verify the dashboard API is reachable

```bash
curl -s http://localhost:9119/api/plugins/hermes-peer/health | python3 -m json.tool
```

Expected: `{"ok": true, "backend": "posix", ...}`.

If this returns a 404, the dashboard has not rescanned plugins. Restart the
dashboard.

### Verify the frontend bundle is served

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9119/dashboard-plugins/hermes-peer/index.js
```

Expected: `200`. A 404 means the `dist/` directory is missing or the
dashboard hasn't picked up the plugin.

### Check the browser console

Open the dashboard in a browser, navigate to the Walkie-Talkie tab, and
open DevTools (F12). Look for:

- `Dashboard host SDK not available` — the plugin is loaded outside the
  dashboard (e.g., opened as a standalone HTML file). It must run inside
  the Hermes Dashboard.
- `WebSocket connection to ... failed` — the events socket couldn't
  connect. The plugin falls back to polling (refresh on tab focus). Check
  that the dashboard is running and the WebSocket endpoint is reachable.

### Plugin tab not appearing

1. Confirm the plugin is enabled: `hermes plugins list`
2. Confirm `manifest.json` exists at the expected path:
   `ls ~/.hermes/hermes-agent/plugins/hermes-peer/dashboard/manifest.json`
3. Restart the dashboard
4. Check dashboard startup logs for plugin scan errors

## Uninstall

```bash
hermes plugins remove hermes-peer
```

This removes the plugin directory from `~/.hermes/hermes-agent/plugins/`.
The dashboard tab disappears on next restart.

To also remove the Python package:

```bash
pip uninstall hermes-walkie-talkie
```

## Public API only

This plugin uses only the public Hermes Dashboard Plugin SDK surface:

- `window.__HERMES_PLUGIN_SDK__` — React, hooks, `fetchJSON`, `buildWsUrl`,
  `api.getActiveProfile()`, `utils`, `components`
- `window.__HERMES_PLUGINS__` — `register(name, Component)`

It does not import from `hermes_cli`, read `kanban.db`, access the
filesystem directly, or depend on any Hermes internal module. The SDK
contract is defined in the host's `web/src/plugins/sdk.d.ts`.
