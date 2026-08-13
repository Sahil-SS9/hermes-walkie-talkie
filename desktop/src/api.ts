/**
 * Typed REST/socket wrappers over the Hermes Peer dashboard plugin API.
 *
 * All reads go through `ctx.rest` (namespace-scoped to /api/plugins/
 * hermes-peer) — the sanctioned door (G6.6). The socket is an accelerator;
 * polling remains the authoritative fallback (G6.7).
 */

import type { PluginContext } from '@hermes/plugin-sdk'

export interface PeerView {
  peer_id: string
  agent_id: string
  name: string
  profile: string
  surface: string
  status: string
  cwd: string
  git_branch: string
}

export interface GroupView {
  group_id: string
  name: string
  owner_agent_id: string
  members: number
}

export interface MemberView {
  agent_id: string
  peer_id: string
}

export interface BroadcastChildView {
  agent_id: string
  peer_id: string
  child_message_id: string
  state: string
  detail: string
}

export interface InboxRowView {
  message_id: string
  state: string
  sender_peer_id: string
  content: string
}

export interface RequestView {
  request_id: string
  sender_agent_id: string
  state: string
  summary: string
  created_at: string
  deadline: string | null
}

export interface HealthView {
  ok: boolean
  backend: string
  runtime_dir: string
  registry_entries: number
  live_peers: number
  pending_messages: number
  held_messages: number
  problems: Array<{ severity: string; problem: string; remedy: string }>
}

export interface EventsFrame {
  events: Array<{ kind: string; [key: string]: unknown }>
}

export interface PeerApi {
  health(): Promise<HealthView>
  metrics(): Promise<Record<string, unknown>>
  peers(): Promise<{ peers: PeerView[] }>
  groups(): Promise<{ groups: GroupView[] }>
  createGroup(name: string): Promise<GroupView>
  groupMembers(groupId: string): Promise<{ group_id: string; members: MemberView[] }>
  addMember(groupId: string, agentId: string): Promise<{ added: boolean }>
  broadcastOutcomes(broadcastId: string): Promise<{ per_member: BroadcastChildView[] }>
  inbox(): Promise<{ messages: InboxRowView[] }>
  requests(): Promise<{ requests: RequestView[] }>
  requestDetail(requestId: string): Promise<RequestView>
  respond(requestId: string, action: string, detail?: string): Promise<RequestView>
  onEvents(fn: (frame: EventsFrame) => void): () => void
}

export function createPeerApi(ctx: PluginContext): PeerApi {
  return {
    health: () => ctx.rest<HealthView>('/health'),
    metrics: () => ctx.rest<Record<string, unknown>>('/metrics'),
    peers: () => ctx.rest<{ peers: PeerView[] }>('/peers'),
    groups: () => ctx.rest<{ groups: GroupView[] }>('/groups'),
    createGroup: (name) => ctx.rest<GroupView>('/groups', { method: 'POST', body: { name } }),
    groupMembers: (groupId) => ctx.rest<{ group_id: string; members: MemberView[] }>(`/groups/${groupId}/members`),
    addMember: (groupId, agentId) =>
      ctx.rest<{ added: boolean }>(`/groups/${groupId}/members`, { method: 'POST', body: { agent_id: agentId } }),
    broadcastOutcomes: (broadcastId) =>
      ctx.rest<{ per_member: BroadcastChildView[] }>(`/broadcasts/${broadcastId}`),
    inbox: () => ctx.rest<{ messages: InboxRowView[] }>('/inbox'),
    requests: () => ctx.rest<{ requests: RequestView[] }>('/requests'),
    requestDetail: (requestId) => ctx.rest<RequestView>(`/requests/${requestId}`),
    respond: (requestId, action, detail = '') =>
      ctx.rest<RequestView>(`/requests/${requestId}/respond`, {
        method: 'POST',
        body: { action, detail },
      }),
    onEvents: (fn) => ctx.socket('/events', (data) => fn(data as EventsFrame)),
  }
}
