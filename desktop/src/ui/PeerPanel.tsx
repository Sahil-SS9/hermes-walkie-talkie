/**
 * Peer panel — tabs for Peers, Groups, Inbox, Requests, Health (P8.5).
 *
 * Presence remediation (G8): the Peers section becomes an expanded,
 * selectable list (Claude-Code-style). Arrow keys / click select a peer
 * (row gets `.sel`), Enter activates the focused action, Esc collapses.
 * Per-peer actions map 1:1 to existing commands: Focus (show detail),
 * Send (peer-send via a prompt), Copy ID, Policy (peer-policy via a
 * prompt), Inbox (peer-inbox), Dashboard (open the dashboard tab),
 * Group (peer-group), Broadcast (peer-broadcast), Refresh.
 */

import { useEffect, useState } from 'react'
import type { PluginContext } from '@hermes/plugin-sdk'

import type { PeerApi, PeerView } from '../api'
import type { PeerUiState } from '../store'

export interface PeerPanelProps {
  ctx: PluginContext
  api: PeerApi
  state: PeerUiState
  refresh: () => Promise<void>
  switchProfile: (profile: string) => void
}

export interface PeerAction {
  key: string
  label: string
  run: (peer: PeerView) => void
  disabled?: boolean
}

export function buildPeerActions(api: PeerApi, refresh: () => Promise<void>): PeerAction[] {
  return [
    // C1: Focus/Inbox/Dashboard/Group/Broadcast have no host navigation seam
    // yet — ship them disabled rather than rendering buttons that do nothing.
    { key: 'f', label: 'Focus', run: () => {}, disabled: true },
    {
      key: 's',
      label: 'Send',
      run: (peer) => {
        const content = window.prompt(`Send message to ${peer.name || peer.agent_id.slice(0, 8)}:`)
        if (!content) return
        // C8: surface failures instead of swallowing them (unhandled rejection).
        void api.send(peer.peer_id, content).then(() => refresh()).catch((err) => {
          window.alert(`Send failed: ${String(err?.message || err)}`)
        })
      },
    },
    {
      key: 'c',
      label: 'Copy ID',
      run: async (peer) => {
        try {
          await navigator.clipboard.writeText(peer.agent_id || peer.peer_id)
        } catch {
          /* clipboard unavailable in some hosts */
        }
      },
    },
    {
      key: 'p',
      label: 'Policy',
      run: (peer) => {
        const policy = window.prompt(`Set inbound policy for ${peer.name || peer.agent_id.slice(0, 8)} (accept|hold|refuse):`, 'accept')
        if (!policy) return
        const normalized = policy.trim().toLowerCase()
        if (!['accept', 'hold', 'refuse'].includes(normalized)) {
          window.alert(`Invalid policy '${normalized}'; expected accept|hold|refuse`)
          return
        }
        // C8: surface failures instead of swallowing them.
        void api.policy(peer.peer_id, normalized).then(() => refresh()).catch((err) => {
          window.alert(`Policy failed: ${String(err?.message || err)}`)
        })
      },
    },
    { key: 'i', label: 'Inbox', run: () => {}, disabled: true },
    { key: 'd', label: 'Dashboard', run: () => {}, disabled: true },
    { key: 'g', label: 'Group', run: () => {}, disabled: true },
    { key: 'b', label: 'Broadcast', run: () => {}, disabled: true },
    { key: 'r', label: 'Refresh', run: () => void refresh() },
  ]
}

export function PeerPanel(props: PeerPanelProps) {
  const { ctx, api, state, refresh } = props
  const [tab, setTab] = useState<'peers' | 'groups' | 'inbox' | 'requests' | 'health'>('peers')
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    void refresh()
    const off = api.onEvents(() => void refresh())
    return off
  }, [api, refresh])

  const tabs = [
    ['peers', 'Peers'],
    ['groups', 'Groups'],
    ['inbox', 'Inbox'],
    ['requests', 'Requests'],
    ['health', 'Health'],
  ] as const

  const selectNext = (dir: 1 | -1) => {
    if (!state.peers.length) return
    const idx = state.peers.findIndex((p) => p.peer_id === selected)
    const next = (idx === -1 ? (dir === 1 ? -1 : 0) : idx + dir + state.peers.length) % state.peers.length
    setSelected(state.peers[next].peer_id)
  }

  return (
    <div
      className="hermes-peer-panel"
      onKeyDown={(e) => {
        if (tab !== 'peers') return
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          selectNext(1)
        } else if (e.key === 'ArrowUp') {
          e.preventDefault()
          selectNext(-1)
        } else if (e.key === 'Enter' && selected) {
          const peer = state.peers.find((p) => p.peer_id === selected)
          if (peer) {
            e.preventDefault()
            // C1: Enter acts on the first ENABLED action (Focus is a stub).
            const action = buildPeerActions(api, refresh).find((a) => !a.disabled)
            if (action) action.run(peer)
          }
        } else if (e.key === 'Escape') {
          setSelected(null)
        }
      }}
    >
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
        {tab === 'peers' ? (
          <PeersSection
            peers={state.peers}
            summary={state.summary}
            selected={selected}
            onSelect={setSelected}
            onActivate={(peer) => {
              if (!peer) return
              const action = buildPeerActions(api, refresh).find((a) => a.key === 'f')
              action?.run(peer)
            }}
          />
        ) : null}
        {tab === 'groups' ? <GroupsSection api={api} refresh={refresh} /> : null}
        {tab === 'inbox' ? <InboxSection api={api} /> : null}
        {tab === 'requests' ? <RequestsSection requests={state.requests} /> : null}
        {tab === 'health' ? <HealthSection ctx={ctx} /> : null}
      </div>
      <div className="hermes-peer-actions" data-testid="peer-actions">
        {buildPeerActions(api, refresh).map((a) => (
          <button
            key={a.key}
            className="hermes-peer-act"
            data-action={a.key}
            disabled={!selected || a.disabled}
            onClick={() => {
              const peer = state.peers.find((p) => p.peer_id === selected)
              if (peer) a.run(peer)
            }}
          >
            <kbd>{a.key}</kbd> {a.label}
          </button>
        ))}
      </div>
      <div className="hermes-peer-hint">↑↓ select · Enter act · Esc close</div>
    </div>
  )
}

function PeersSection({
  peers,
  summary,
  selected,
  onSelect,
  onActivate,
}: {
  peers: PeerView[]
  summary: PeerUiState['summary']
  selected: string | null
  onSelect: (id: string | null) => void
  onActivate: (peer: PeerView | null) => void
}) {
  if (!peers.length) return <p className="hermes-peer-muted">No live peers.</p>
  const youId = summary?.you_peer_id ?? null
  return (
    <ul className="hermes-peer-list" role="listbox">
      {peers.map((p) => {
        const offline = (summary?.peers || []).some((s) => s.peer_id === p.peer_id && s.offline)
        const label = offline ? 'offline' : p.status
        const dot = offline ? 'r' : p.status === 'working' ? 'g' : p.status === 'held' || p.status === 'closing' ? 'a' : 'q'
        const isMe = p.peer_id === youId
        const sel = p.peer_id === selected
        return (
          <li
            key={p.agent_id}
            role="option"
            aria-selected={sel}
            className={`hermes-peer-row${sel ? ' sel' : ''}${isMe ? ' me' : ''}${offline ? ' off' : ''}`}
            onClick={() => onSelect(p.peer_id)}
            onDoubleClick={() => onActivate(p)}
          >
            <span className={`hermes-peer-dot dot ${dot}`} />
            <span className="hermes-peer-row-title">
              {p.name || p.agent_id.slice(0, 8)}
              {isMe ? <span className="hermes-peer-you">you</span> : null}
            </span>
            <span className="hermes-peer-row-meta">
              {p.surface} · {label}
              {p.current_activity ? ` · ${p.current_activity}` : ''}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function GroupsSection({ api, refresh }: { api: PeerApi; refresh: () => Promise<void> }) {
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
  requests,
}: {
  requests: Array<{ request_id: string; state: string; summary: string }>
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
