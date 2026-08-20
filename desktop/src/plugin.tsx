/**
 * Hermes Peer Desktop plugin — first-class panel + status bar item (P8.4).
 *
 * Presence remediation (G7/G8): the status-bar contribution becomes a
 * stateful ambient pill (`● 2 peers live · you: KENSEI · 1 offline ·
 * live 2s`) whose click opens the expanded peer panel via openWorkspace;
 * a Ctrl+P keybind contribution does the same. The panel reuses the
 * same summary-driven state as the pill.
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
import { createRefresher, emptyState, statusPillLabel, type PeerUiState } from './store'
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
    // S6: host chrome capability is duck-typed; only openWorkspace is used.
    const chrome = ctx as unknown as { openWorkspace?: (id: string, opts: { render: () => unknown; title?: string }) => void }

    // ---- state (per-profile) -------------------------------------------------
    let currentProfile = 'default'
    let state: PeerUiState = emptyState()
    // R2: keep the LATEST state in a ref so the open panel (which captured an
    // early render closure) reads fresh data, not a stale snapshot.
    let stateRef: PeerUiState = state
    let disposed = false // R3: guard onState after teardown.
    let notify: (s: PeerUiState) => void = () => {}

    const refresh = createRefresher(api, (s) => {
      if (disposed) return // R3: never setState after deactivate.
      state = s
      stateRef = s
      notify(s)
    })

    const switchProfile = (next: string) => {
      if (next === currentProfile) return
      currentProfile = next
      state = emptyState() // never leak another profile's data (G6.8)
      stateRef = state
      void refresh()
    }

    // ---- status bar pill (stateful ambient chrome, G7) -----------------------
    // render is invoked by the host whenever the contribution is drawn;
    // notify() re-renders the pill when state changes.
    let pillRoot: HTMLElement | null = null
    notify = (s: PeerUiState) => {
      if (pillRoot) {
        pillRoot.textContent = statusPillLabel(s)
        pillRoot.classList.toggle('hermes-peer-pill-off', (s.summary?.offline_count ?? 0) > 0)
      }
    }

    const openPanel = () => {
      if (typeof chrome.openWorkspace === 'function') {
        chrome.openWorkspace('hermes-peer', {
          title: 'Peers',
          // R2: read live state via stateRef so the panel updates after
          // refreshes instead of freezing on the captured object.
          render: () => PeerPanel({ ctx, api, state: stateRef, refresh, switchProfile }),
        })
      }
      // S6: no CustomEvent fallback — the secondarySidebar contribution is
      // registered below; the pill opens the panel when the host supports it.
    }

    disposers.push(
      ctx.register({
        id: 'peer-status',
        // H4: the host's STATUSBAR_AREAS uses exact-match keys
        // (statusBar.left/statusBar.right) — 'statusBar' rendered nowhere.
        area: 'statusBar.left',
        title: 'peer',
        order: 30,
        render: () => {
          const el = document.createElement('button')
          el.className = 'hermes-peer-pill'
          el.textContent = statusPillLabel(state)
          el.title = 'Peers — click for the expanded panel (Ctrl+P)'
          el.setAttribute('aria-label', 'Peer sessions: open expanded panel')
          // C6: AbortController so the disposer removes the listener (no leak
          // on host re-render of the statusBar contribution).
          const ac = new AbortController()
          el.addEventListener('click', openPanel, { signal: ac.signal })
          disposers.push(() => ac.abort())
          pillRoot = el
          notify(state)
          return el
        },
      })
    )

    // ---- keybind: Ctrl+P opens the expanded panel (G8) -----------------------
    if (typeof chrome.openWorkspace === 'function') {
      disposers.push(
        ctx.register({
          id: 'peer-open-panel',
          area: 'keybinds',
          title: 'Open peer panel',
          order: 30,
          render: () => ({
            keybind: 'mod+p',
            handler: () => openPanel(),
          }),
        })
      )
    }

    // ---- panel contribution --------------------------------------------------
    const renderPanel = () => {
      return PeerPanel({
        ctx,
        api,
        state: stateRef, // R2: live state, not a stale capture.
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
      disposed = true // R3: block any in-flight onState after teardown.
      for (const d of disposers) d()
      pillRoot = null
    }
  },
}

export default plugin
