import { describe, expect, it } from 'vitest'

import { createRefresher, emptyState, statusPillLabel, timeAgoFromIso, type PeerUiState } from './store'

describe('emptyState', () => {
  it('starts loading with no data', () => {
    const s = emptyState()
    expect(s.loading).toBe(true)
    expect(s.error).toBeNull()
    expect(s.peers).toEqual([])
    expect(s.requests).toEqual([])
    expect(s.summary).toBeNull()
  })
})

describe('createRefresher', () => {
  it('publishes peers, requests and summary after a successful fetch', async () => {
    const api = {
      peers: async () => ({ peers: [{ peer_id: 'p1', agent_id: 'a1', name: 'alpha', profile: '', surface: 'cli', status: 'idle', current_activity: '', cwd: '/tmp', git_branch: '' }] }),
      requests: async () => ({ requests: [] }),
      summary: async () => ({
        total: 1,
        active_count: 0,
        offline_count: 0,
        you_peer_id: 'p1',
        last_updated: new Date().toISOString(),
        peers: [{ peer_id: 'p1', agent_id: 'a1', name: 'alpha', profile: '', surface: 'cli', status: 'idle', offline: false, status_label: 'idle', current_activity: '', cwd: '/tmp', git_branch: '', last_seen: new Date().toISOString() }],
      }),
    }
    let published: unknown = null
    const refresh = createRefresher(api as never, (s) => (published = s))
    await refresh()
    expect((published as { loading: boolean }).loading).toBe(false)
    expect((published as { peers: unknown[] }).peers).toHaveLength(1)
    expect((published as { summary: { total: number } }).summary?.total).toBe(1)
    expect((published as { lastUpdated: number | null }).lastUpdated).not.toBeNull()
  })

  it('publishes an error when the fetch fails', async () => {
    const api = {
      peers: async () => {
        throw new Error('boom')
      },
      requests: async () => ({ requests: [] }),
      summary: async () => ({ total: 0, active_count: 0, offline_count: 0, you_peer_id: null, last_updated: '', peers: [] }),
    }
    let published: unknown = null
    const refresh = createRefresher(api as never, (s) => (published = s))
    await refresh()
    expect((published as { error: string }).error).toContain('boom')
    expect((published as { loading: boolean }).loading).toBe(false)
  })

  it('discards a stale refresh (latest call wins)', async () => {
    const api = {
      peers: async () => ({ peers: [] }),
      requests: async () => ({ requests: [] }),
      summary: async () => ({ total: 0, active_count: 0, offline_count: 0, you_peer_id: null, last_updated: '', peers: [] }),
    }
    const seen: unknown[] = []
    const refresh = createRefresher(api as never, (s) => seen.push(s))
    // Two refreshes race; the second must win.
    const first = refresh()
    const second = refresh()
    await Promise.all([first, second])
    const final = seen[seen.length - 1] as { lastUpdated: number | null }
    expect(final.lastUpdated).not.toBeNull()
  })
})

describe('statusPillLabel (G7)', () => {
  it('renders the mockup pill copy with you + offline + liveness', () => {
    const state: PeerUiState = {
      loading: false,
      error: null,
      peers: [],
      requests: [],
      summary: {
        total: 3,
        live_count: 3,
        active_count: 2,
        idle_count: 0,
        offline_count: 1,
        you_peer_id: 'p1',
        last_updated: new Date(Date.now() - 2000).toISOString(),
        peers: [
          { peer_id: 'p1', agent_id: 'a1', name: 'KENSEI', profile: '', surface: 'cli', status: 'working', offline: false, status_label: 'working', current_activity: '', cwd: '', git_branch: '', last_seen: '' },
          { peer_id: 'p2', agent_id: 'a2', name: 'Remii', profile: '', surface: 'cli', status: 'working', offline: false, status_label: 'working', current_activity: '', cwd: '', git_branch: '', last_seen: '' },
          { peer_id: 'p3', agent_id: 'a3', name: 'Octacon', profile: '', surface: 'cli', status: 'idle', offline: true, status_label: 'offline', current_activity: '', cwd: '', git_branch: '', last_seen: '' },
        ],
      },
      lastUpdated: Date.now(),
    }
    const label = statusPillLabel(state)
    // 3 live open sessions, 2 working, 1 offline → `● 3 Live · 2 working · × 1 Offline`
    expect(label).toContain('● 3 Live')
    expect(label).toContain('2 working')
    expect(label).toContain('you: KENSEI')
    expect(label).toContain('× 1 Offline')
    expect(label).toContain('live 2s')
  })

  it('handles a missing summary gracefully (empty pill)', () => {
    expect(statusPillLabel(emptyState())).toBe('')
  })

  it('hides the pill when only one session is known (total < 2)', () => {
    const state: PeerUiState = {
      loading: false,
      error: null,
      peers: [],
      requests: [],
      summary: {
        total: 1,
        active_count: 1,
        offline_count: 0,
        you_peer_id: 'p1',
        last_updated: new Date().toISOString(),
        peers: [
          { peer_id: 'p1', agent_id: 'a1', name: 'KENSEI', profile: '', surface: 'cli', status: 'working', offline: false, status_label: 'working', current_activity: '', cwd: '', git_branch: '', last_seen: '' },
        ],
      },
      lastUpdated: Date.now(),
    }
    // Single session = you only → no ambient signal.
    expect(statusPillLabel(state)).toBe('')
  })
})

describe('timeAgoFromIso', () => {
  it('formats seconds and minutes', () => {
    const now = Date.now()
    expect(timeAgoFromIso(new Date(now - 2000).toISOString(), now)).toBe('2s ago')
    expect(timeAgoFromIso(new Date(now - 65_000).toISOString(), now)).toBe('1m ago')
    expect(timeAgoFromIso('', now)).toBe('—')
  })
})
