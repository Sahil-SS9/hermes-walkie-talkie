import { describe, expect, it } from 'vitest'

import { createPeerApi } from './api'
import type { PluginContext } from './sdk-stub.d'

describe('createPeerApi', () => {
  it('routes every call through ctx.rest (namespace-scoped)', async () => {
    const calls: Array<{ path: string; opts?: unknown }> = []
    const ctx = {
      rest: async <T>(path: string, opts?: unknown): Promise<T> => {
        calls.push({ path, opts })
        return {} as T
      },
      socket: () => () => {},
    } as unknown as PluginContext

    const api = createPeerApi(ctx)
    await api.health()
    await api.peers()
    await api.summary()
    await api.groups()
    await api.createGroup('team')
    await api.broadcastOutcomes('b1')
    await api.send('p1', 'hello')
    await api.policy('p1', 'hold')

    expect(calls.map((c) => c.path)).toEqual([
      '/health',
      '/peers',
      '/peers/summary',
      '/groups',
      '/groups',
      '/broadcasts/b1',
      '/peers/p1/messages',
      '/peers/p1/policy',
    ])
    expect(calls[4].opts).toMatchObject({ method: 'POST', body: { name: 'team' } })
    expect(calls[6].opts).toMatchObject({ method: 'POST', body: { content: 'hello' } })
    expect(calls[7].opts).toMatchObject({ method: 'POST', body: { policy: 'hold' } })
  })

  it('returns a socket disposer for events', () => {
    let disposed = false
    const ctx = {
      rest: async () => ({}),
      socket: () => () => {
        disposed = true
      },
    } as unknown as PluginContext
    const api = createPeerApi(ctx)
    const off = api.onEvents(() => {})
    off()
    expect(disposed).toBe(true)
  })
})
