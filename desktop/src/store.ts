/**
 * Profile-scoped UI state for the Peer panel.
 *
 * The cache is keyed by active profile so switching profiles never leaks
 * another profile's peers/inbox into view (G6.8). The socket is an
 * accelerator over polling; a failed socket falls back silently.
 */

import type { PeerApi, PeerView, RequestView } from './api'

export interface PeerUiState {
  loading: boolean
  error: string | null
  peers: PeerView[]
  requests: RequestView[]
  lastUpdated: number | null
}

export function emptyState(): PeerUiState {
  return { loading: true, error: null, peers: [], requests: [], lastUpdated: null }
}

/**
 * Create a refresh function bound to one profile. Call it on activation,
 * on profile switch, and after any mutation. It is safe to call
 * concurrently — the latest call wins via a monotonic token.
 */
export function createRefresher(api: PeerApi, onState: (s: PeerUiState) => void) {
  let token = 0

  return async function refresh(): Promise<void> {
    const my = ++token
    onState({ ...emptyState(), loading: true })
    try {
      const [peers, requests] = await Promise.all([api.peers(), api.requests()])
      if (my !== token) return // a newer refresh superseded us
      onState({
        loading: false,
        error: null,
        peers: peers.peers,
        requests: requests.requests,
        lastUpdated: Date.now(),
      })
    } catch (err) {
      if (my !== token) return
      onState({ ...emptyState(), loading: false, error: String(err) })
    }
  }
}

/**
 * Bounded in-memory event ring used to render "live" activity. Kept
 * content-free (kind + ids only) — never message bodies (G1.2).
 */
export interface ActivityItem {
  kind: string
  id: string
  at: number
}

export const MAX_ACTIVITY = 50

export function appendActivity(existing: ActivityItem[], frame: { events: Array<{ kind: string }> }): ActivityItem[] {
  const items = frame.events.map((ev) => ({
    kind: ev.kind,
    id: `${ev.kind}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    at: Date.now(),
  }))
  return [...existing, ...items].slice(-MAX_ACTIVITY)
}
