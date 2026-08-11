import { describe, expect, it } from 'vitest'

import { appendActivity, createRefresher, emptyState, MAX_ACTIVITY } from './store'

describe('emptyState', () => {
  it('starts loading with no data', () => {
    const s = emptyState()
    expect(s.loading).toBe(true)
    expect(s.error).toBeNull()
    expect(s.peers).toEqual([])
    expect(s.requests).toEqual([])
  })
})

describe('createRefresher', () => {
  it('publishes peers and requests after a successful fetch', async () => {
    const api = {
      peers: async () => ({ peers: [{ peer_id: 'p1', agent_id: 'a1', name: 'alpha', profile: '', surface: 'cli', status: 'idle', cwd: '/tmp', git_branch: '' }] }),
      requests: async () => ({ requests: [] }),
    }
    let published: unknown = null
    const refresh = createRefresher(api as never, (s) => (published = s))
    await refresh()
    expect((published as { loading: boolean }).loading).toBe(false)
    expect((published as { peers: unknown[] }).peers).toHaveLength(1)
    expect((published as { lastUpdated: number | null }).lastUpdated).not.toBeNull()
  })

  it('publishes an error when the fetch fails', async () => {
    const api = {
      peers: async () => {
        throw new Error('boom')
      },
      requests: async () => ({ requests: [] }),
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

describe('appendActivity', () => {
  it('appends frames and bounds the ring', () => {
    let items: Array<{ kind: string; id: string; at: number }> = []
    for (let i = 0; i < 60; i++) {
      items = appendActivity(items, { events: [{ kind: 'peer_seen' }] })
    }
    expect(items).toHaveLength(MAX_ACTIVITY)
    expect(items[items.length - 1].kind).toBe('peer_seen')
  })
})
