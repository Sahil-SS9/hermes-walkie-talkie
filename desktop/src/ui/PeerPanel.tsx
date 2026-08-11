/**
 * Peer panel — tabs for Peers, Groups, Inbox, Requests, Health (P8.5).
 *
 * Every section renders content-free metadata and bounded data; the
 * broadcast section surfaces per-recipient outcomes (P8.6). Mutations go
 * through ctx.rest and then refresh.
 */

import { useCallback, useEffect, useState } from 'react'
import type { PluginContext } from '@hermes/plugin-sdk'

import type { PeerApi } from '../api'
import type { PeerUiState } from '../store'

export interface PeerPanelProps {
  ctx: PluginContext
  api: PeerApi
  state: PeerUiState
  refresh: () => Promise<void>
  switchProfile: (profile: string) => void
}

export function PeerPanel(props: PeerPanelProps) {
  const { ctx, api, state, refresh } = props
  const [tab, setTab] = useState<'peers' | 'groups' | 'inbox' | 'requests' | 'health'>('peers')
  const [profile, setProfile] = useState('default')

  useEffect(() => {
    void refresh()
    const off = api.onEvents(() => void refresh())
    return off
  }, [api, refresh, profile])

  const changeProfile = useCallback(
    (next: string) => {
      setProfile(next)
      props.switchProfile(next)
    },
    [props]
  )

  const tabs = [
    ['peers', 'Peers'],
    ['groups', 'Groups'],
    ['inbox', 'Inbox'],
    ['requests', 'Requests'],
    ['health', 'Health'],
  ] as const

  return (
    <div className="hermes-peer-panel">
      <div className="hermes-peer-tabs">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? 'hermes-peer-tab active' : 'hermes-peer-tab'}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="hermes-peer-body">
        {state.loading ? <p className="hermes-peer-muted">Loading…</p> : null}
        {state.error ? <p className="hermes-peer-error">{state.error}</p> : null}
        {tab === 'peers' ? <PeersSection peers={state.peers} /> : null}
        {tab === 'groups' ? <GroupsSection ctx={ctx} api={api} refresh={refresh} /> : null}
        {tab === 'inbox' ? <InboxSection api={api} /> : null}
        {tab === 'requests' ? <RequestsSection api={api} requests={state.requests} refresh={refresh} /> : null}
        {tab === 'health' ? <HealthSection ctx={ctx} /> : null}
      </div>
    </div>
  )
}

function PeersSection({ peers }: { peers: Array<{ name: string; agent_id: string; surface: string; status: string }> }) {
  if (!peers.length) return <p className="hermes-peer-muted">No live peers.</p>
  return (
    <ul className="hermes-peer-list">
      {peers.map((p) => (
        <li key={p.agent_id} className="hermes-peer-row">
          <span className="hermes-peer-row-title">{p.name || p.agent_id.slice(0, 8)}</span>
          <span className="hermes-peer-row-meta">
            {p.surface} · {p.status}
          </span>
        </li>
      ))}
    </ul>
  )
}

function GroupsSection({ ctx, api, refresh }: { ctx: PluginContext; api: PeerApi; refresh: () => Promise<void> }) {
  const [groups, setGroups] = useState<Array<{ group_id: string; name: string; members: number }>>([])
  const [name, setName] = useState('')

  useEffect(() => {
    void api.groups().then((r) => setGroups(r.groups))
  }, [api, refresh])

  const create = () => {
    if (!name.trim()) return
    void api
      .createGroup(name.trim())
      .then(() => setName(''))
      .then(() => api.groups())
      .then((r) => setGroups(r.groups))
  }

  return (
    <div>
      <div className="hermes-peer-form">
        <input value={name} placeholder="Group name" onChange={(e) => setName(e.target.value)} />
        <button onClick={create}>Create</button>
      </div>
      {!groups.length ? <p className="hermes-peer-muted">No groups.</p> : null}
      <ul className="hermes-peer-list">
        {groups.map((g) => (
          <li key={g.group_id} className="hermes-peer-row">
            <span className="hermes-peer-row-title">{g.name}</span>
            <span className="hermes-peer-row-meta">{g.members} members</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function InboxSection({ api }: { api: PeerApi }) {
  const [messages, setMessages] = useState<Array<{ message_id: string; state: string; content: string }>>([])

  useEffect(() => {
    void api.inbox().then((r) => setMessages(r.messages))
  }, [api])

  if (!messages.length) return <p className="hermes-peer-muted">Inbox empty.</p>
  return (
    <ul className="hermes-peer-list">
      {messages.map((m) => (
        <li key={m.message_id} className="hermes-peer-row">
          <span className="hermes-peer-row-title">[{m.state}]</span>
          <span className="hermes-peer-row-meta">{m.content.slice(0, 60)}</span>
        </li>
      ))}
    </ul>
  )
}

function RequestsSection({
  api,
  requests,
  refresh,
}: {
  api: PeerApi
  requests: Array<{ request_id: string; state: string; summary: string }>
  refresh: () => Promise<void>
}) {
  if (!requests.length) return <p className="hermes-peer-muted">No requests.</p>
  return (
    <ul className="hermes-peer-list">
      {requests.map((r) => (
        <li key={r.request_id} className="hermes-peer-row">
          <span className="hermes-peer-row-title">[{r.state}]</span>
          <span className="hermes-peer-row-meta">{r.summary}</span>
        </li>
      ))}
    </ul>
  )
}

function HealthSection({ ctx }: { ctx: PluginContext }) {
  const [health, setHealth] = useState<{ ok: boolean; backend: string; problems: Array<{ problem: string; remedy: string }> } | null>(null)

  useEffect(() => {
    void ctx.rest('/health').then((h) => setHealth(h as typeof health))
  }, [ctx])

  if (!health) return <p className="hermes-peer-muted">Checking…</p>
  return (
    <div>
      <p className="hermes-peer-row-title">
        {health.ok ? 'Healthy' : 'Unhealthy'} · backend {health.backend}
      </p>
      {!health.problems.length ? <p className="hermes-peer-muted">No problems.</p> : null}
      <ul className="hermes-peer-list">
        {health.problems.map((p, i) => (
          <li key={i} className="hermes-peer-row">
            <span className="hermes-peer-row-title">{p.problem}</span>
            <span className="hermes-peer-row-meta">{p.remedy}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
