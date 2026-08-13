/**
 * Typed API client for the Walkie-Talkie Dashboard plugin.
 *
 * All reads go through the host-injected `__HERMES_DASHBOARD_API__` which
 * namespace-scopes REST calls to /api/plugins/hermes-peer. The socket is
 * an accelerator; polling remains the authoritative fallback.
 */

export interface DashboardHost {
  rest<T = any>(path: string, opts?: { method?: string; body?: unknown }): Promise<T>;
  socket(path: string, onMessage: (data: any) => void): () => void;
  profile: string;
}

export interface PeerView {
  peer_id: string;
  agent_id: string;
  name: string;
  profile: string;
  surface: string;
  status: string;
  cwd: string;
  git_branch: string;
}

export interface GroupView {
  group_id: string;
  name: string;
  owner_agent_id: string;
  members: number;
}

export interface InboxRowView {
  message_id: string;
  state: string;
  sender_peer_id: string;
  content: string;
}

export interface RequestView {
  request_id: string;
  sender_agent_id: string;
  state: string;
  summary: string;
  created_at: string;
  deadline: string | null;
}

export interface HealthView {
  ok: boolean;
  backend: string;
  runtime_dir: string;
  registry_entries: number;
  live_peers: number;
  pending_messages: number;
  held_messages: number;
  problems: Array<{ severity: string; problem: string; remedy: string }>;
}

export interface BroadcastChildView {
  agent_id: string;
  peer_id: string;
  child_message_id: string;
  state: string;
  detail: string;
}

export interface EventsFrame {
  events: Array<{ kind: string; [key: string]: unknown }>;
}

export function createApi(host: DashboardHost) {
  return {
    health: (): Promise<HealthView> => host.rest('/health'),
    metrics: (): Promise<Record<string, unknown>> => host.rest('/metrics'),
    peers: (): Promise<{ peers: PeerView[] }> => host.rest('/peers'),
    groups: (): Promise<{ groups: GroupView[] }> => host.rest('/groups'),
    createGroup: (name: string): Promise<GroupView> =>
      host.rest('/groups', { method: 'POST', body: { name } }),
    groupMembers: (groupId: string): Promise<{ group_id: string; members: Array<{ agent_id: string; peer_id: string }> }> =>
      host.rest(`/groups/${groupId}/members`),
    addMember: (groupId: string, agentId: string): Promise<{ added: boolean }> =>
      host.rest(`/groups/${groupId}/members`, { method: 'POST', body: { agent_id: agentId } }),
    broadcastOutcomes: (broadcastId: string): Promise<{ per_member: BroadcastChildView[] }> =>
      host.rest(`/broadcasts/${broadcastId}`),
    inbox: (): Promise<{ messages: InboxRowView[] }> => host.rest('/inbox'),
    requests: (): Promise<{ requests: RequestView[] }> => host.rest('/requests'),
    requestDetail: (requestId: string): Promise<RequestView> =>
      host.rest(`/requests/${requestId}`),
    respond: (requestId: string, action: string, detail?: string): Promise<RequestView> =>
      host.rest(`/requests/${requestId}/respond`, {
        method: 'POST',
        body: { action, detail: detail || '' },
      }),
    onEvents: (fn: (frame: EventsFrame) => void): (() => void) =>
      host.socket('/events', fn),
  };
}

export type Api = ReturnType<typeof createApi>;
