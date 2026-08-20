/**
 * Profile-scoped UI state for the Peer panel.
 *
 * The cache is keyed by active profile so switching profiles never leaks
 * another profile's peers/inbox into view (G6.8). The socket is an
 * accelerator over polling; a failed socket falls back silently.
 *
 * Presence remediation: the state now also carries the aggregate summary
 * (active/offline counts, you_peer_id, last_updated) so the status-bar
 * pill and the expanded panel share one data source (G2/G5/G6/G7/G8).
 */

import type { PeerApi, PeerView, RequestView, SummaryView } from './api'

export interface PeerUiState {
  loading: boolean
  error: string | null
  peers: PeerView[]
  requests: RequestView[]
  summary: SummaryView | null
  lastUpdated: number | null
}

export function emptyState(): PeerUiState {
  return { loading: true, error: null, peers: [], requests: [], summary: null, lastUpdated: null }
}

/** Human "Ns ago" stamp from an RFC3339 UTC timestamp. */
export function timeAgoFromIso(iso: string, now: number = Date.now()): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return '—'
  const s = Math.max(0, Math.floor((now - t) / 1000))
  if (s < 2) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  return `${h}h ago`
}

/** Compact ambient pill copy (G7): `● 2 Live · ○ 1 Idle · [profile]`.
 *  Renders ONLY when >= 2 live sessions are open — with a single session the
 *  only peer is you, so the ambient pill hides (same threshold as CLI/TUI).
 *  Live = OPEN interactive sessions (probe-live, non-gateway); Idle = live
 *  but not working; Offline = PID alive but socket-dead. */
export function statusPillLabel(state: PeerUiState): string {
  const s = state.summary
  if (!s) return ''
  const live = (s as { live_count?: number }).live_count ?? 0
  if (live < 2) return ''
  const youName = (s.peers || []).find((p) => p.peer_id === s.you_peer_id)?.name
  const parts: string[] = []
  const active = s.active_count ?? 0
  const idle = (s as { idle_count?: number }).idle_count ?? 0
  const offline = s.offline_count ?? 0
  if (live > 0) parts.push(`● ${live} Live`)
  if (active > 0 && active < live) parts.push(`${active} working`)
  if (idle > 0) parts.push(`○ ${idle} Idle`)
  if (offline > 0) parts.push(`× ${offline} Offline`)
  if (youName) parts.push(`you: ${youName}`)
  if (state.lastUpdated != null && s.last_updated) parts.push(`live ${timeAgoFromIso(s.last_updated)}`)
  return parts.join(' · ')
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
    // H5: allSettled so a missing endpoint (version skew) degrades to
    // partial data instead of blanking the whole surface.
    const settled = await Promise.allSettled([api.peers(), api.requests(), api.summary()])
    if (my !== token) return // a newer refresh superseded us
    const [peers, requests, summary] = settled
    const failed = settled.filter((r) => r.status === 'rejected')
    const firstErr = failed[0] && 'reason' in failed[0]
      ? String((failed[0] as PromiseRejectedResult).reason?.message ?? (failed[0] as PromiseRejectedResult).reason)
      : ''
    onState({
      loading: false,
      error: failed.length > 0
        ? `${failed.length} endpoint(s) failed${firstErr ? `: ${firstErr}` : ''}`
        : null,
      peers: peers.status === 'fulfilled' ? peers.value.peers : [],
      requests: requests.status === 'fulfilled' ? requests.value.requests : [],
      summary: summary.status === 'fulfilled' ? summary.value : null,
      lastUpdated: Date.now(),
    })
  }
}
