/**
 * Hermes Peer — Desktop disk plugin (initial asset, P7).
 *
 * Minimal contract-valid HermesPlugin (verified against the core
 * loadRuntimePlugin contract in P0.8): plain ESM, default export a
 * HermesPlugin { id, label, activate(ctx) -> disposers }, bare specifiers
 * rewritten by the loader, ctx.rest/ctx.socket only — never SQLite.
 *
 * P8 replaces this file with the full checked build (desktop/src -> vite
 * bundle) at the same path. This asset exists so `hermes peer desktop
 * install` is testable end-to-end before the full UI lands.
 */
import { createPlugin } from '@hermes/plugin-sdk'

export default createPlugin({
  id: 'hermes-peer',
  label: 'Hermes Peer',

  activate(ctx) {
    var disposers = []

    if (ctx.statusBar && typeof ctx.statusBar.addItem === 'function') {
      disposers.push(
        ctx.statusBar.addItem({
          id: 'hermes-peer-status',
          label: 'peer: —',
          onClick: function () {
            if (typeof ctx.navigate === 'function') {
              ctx.navigate('/plugins/hermes-peer')
            }
          }
        })
      )
    }

    // Authoritative backend reads via ctx.rest ONLY.
    var refresh = function () {
      return ctx.rest.get('/api/plugins/hermes-peer/health').catch(function () {
        return { error: 'poll-fallback' }
      })
    }
    void refresh

    return disposers
  }
})
