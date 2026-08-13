/**
 * Hermes Peer Desktop plugin — first-class panel + status bar item (P8.4).
 *
 * Contract: default-exports a HermesPlugin; the host's createPluginContext
 * gives us `register` (contribution registry, id-namespaced), `rest`
 * (namespace-scoped to /api/plugins/hermes-peer), `socket` (accelerator),
 * `i18n`, `storage` and `os`. We never touch the registry directly, never
 * read SQLite, never read the filesystem (G6.6).
 */

import type { PluginContext } from '@hermes/plugin-sdk'

import './style.css'
import { createPeerApi } from './api'
import { createRefresher, emptyState, type PeerUiState } from './store'
import { PeerPanel } from './ui/PeerPanel'

export interface HermesPlugin {
  id: string
  label: string
  activate(ctx: PluginContext): () => void
}

const plugin: HermesPlugin = {
  id: 'hermes-peer',
  label: 'Hermes Peer',

  activate(ctx: PluginContext) {
    const api = createPeerApi(ctx)
    const disposers: Array<() => void> = []

    // ---- state (per-profile) -------------------------------------------------
    let currentProfile = 'default'
    let state: PeerUiState = emptyState()
    let notify: (s: PeerUiState) => void = () => {}

    const refresh = createRefresher(api, (s) => {
      state = s
      notify(s)
    })

    const switchProfile = (next: string) => {
      if (next === currentProfile) return
      currentProfile = next
      state = emptyState() // never leak another profile's data (G6.8)
      void refresh()
    }

    // ---- status bar item (declarative contribution, G6.4) --------------------
    disposers.push(
      ctx.register({
        id: 'peer-status',
        area: 'statusBar',
        title: 'peer',
        order: 30,
      })
    )

    // ---- panel contribution --------------------------------------------------
    const renderPanel = () => {
      return PeerPanel({
        ctx,
        api,
        state,
        refresh,
        switchProfile,
      })
    }

    disposers.push(
      ctx.register({
        id: 'peer-panel',
        area: 'secondarySidebar',
        title: ctx.i18n?.t?.('panel.title') ?? 'Peer',
        order: 30,
        render: renderPanel,
      })
    )

    // ---- live accelerator (socket; polling is the fallback) -------------------
    const offEvents = api.onEvents(() => {
      void refresh()
    })
    disposers.push(offEvents)

    // ---- initial load ---------------------------------------------------------
    void refresh()

    return () => {
      for (const d of disposers) d()
    }
  },
}

export default plugin
