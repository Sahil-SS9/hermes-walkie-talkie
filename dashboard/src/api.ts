/**
 * Typed API client for the Walkie-Talkie Dashboard plugin.
 *
 * Adapts the real Hermes Dashboard Plugin SDK
 * (window.__HERMES_PLUGIN_SDK__) to the plugin's internal API surface.
 *
 * REST calls use the host's authenticated fetchJSON; WebSocket events use
 * buildWsUrl + native WebSocket.  No direct SQLite / filesystem reads.
 */

// Re-export the view types (unchanged).
export interface PeerView {
  peer_id: string;
  agent_id: string;
  name: string;
  profile: string;
  surface: string;
  status: string;
  current_activity: string;
  cwd: string;
  git_branch: string;
}

export interface SummaryView {
  total: number;
  live_count?: number;
  active_count: number;
  idle_count?: number;
  offline_count: number;
  // R9: canonical wire key. `you_peer_id` is the backend contract from
  // GET /peers/summary — do NOT rename to camelCase here; internal state
  // mirrors it as AppState.youPeerId (snake wire / camel internal split).
  you_peer_id: string | null;
  last_updated: string;
  peers: Array<{
    peer_id: string;
    agent_id: string;
    name: string;
    profile: string;
    surface: string;
    status: string;
    offline: boolean;
    status_label: string;
    current_activity: string;
    cwd: string;
    git_branch: string;
    last_seen: string;
  }>;
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

export type WsState = 'connecting' | 'connected' | 'reconnecting' | 'closed';

// ---------------------------------------------------------------------------
// SDK surface (the real contract from window.__HERMES_PLUGIN_SDK__)
// ---------------------------------------------------------------------------

export interface HermesPluginSDK {
  readonly sdkVersion: string;
  React: any;
  hooks: {
    useState: any; useEffect: any; useCallback: any;
    useMemo: any; useRef: any; useContext: any; createContext: any;
  };
  api: Record<string, (...args: any[]) => any>;
  fetchJSON: <T = any>(url: string, init?: RequestInit, options?: { allowUnauthorized?: boolean }) => Promise<T>;
  authedFetch: (url: string, init?: RequestInit) => Promise<Response>;
  buildWsUrl: (path: string, params?: Record<string, string>) => Promise<string>;
  buildWsAuthParam: () => Promise<[string, string]>;
  components: Record<string, any>;
  utils: { cn: (...classes: Array<string | false | null | undefined>) => string; timeAgo: (ts: number) => string; isoTimeAgo: (iso: string) => string };
  useI18n: () => any;
}

// ---------------------------------------------------------------------------
// API factory — adapts the real SDK to the plugin's internal surface
// ---------------------------------------------------------------------------

const BASE = '/api/plugins/hermes-peer';

export function createApi(sdk: HermesPluginSDK) {
  return {
    health: (): Promise<HealthView> => sdk.fetchJSON(`${BASE}/health`),
    metrics: (): Promise<Record<string, unknown>> => sdk.fetchJSON(`${BASE}/metrics`),
    peers: (): Promise<{ peers: PeerView[] }> => sdk.fetchJSON(`${BASE}/peers`),
    summary: (): Promise<SummaryView> => sdk.fetchJSON(`${BASE}/peers/summary`),
    groups: (): Promise<{ groups: GroupView[] }> => sdk.fetchJSON(`${BASE}/groups`),
    createGroup: (name: string): Promise<GroupView> =>
      sdk.fetchJSON(`${BASE}/groups`, { method: 'POST', body: JSON.stringify({ name }), headers: { 'Content-Type': 'application/json' } }),
    groupMembers: (groupId: string): Promise<{ group_id: string; members: Array<{ agent_id: string; peer_id: string }> }> =>
      sdk.fetchJSON(`${BASE}/groups/${encodeURIComponent(groupId)}/members`),
    addMember: (groupId: string, agentId: string): Promise<{ added: boolean }> =>
      sdk.fetchJSON(`${BASE}/groups/${encodeURIComponent(groupId)}/members`, { method: 'POST', body: JSON.stringify({ agent_id: agentId }), headers: { 'Content-Type': 'application/json' } }),
    broadcastOutcomes: (broadcastId: string): Promise<{ per_member: BroadcastChildView[] }> =>
      sdk.fetchJSON(`${BASE}/broadcasts/${encodeURIComponent(broadcastId)}`),
    inbox: (): Promise<{ messages: InboxRowView[] }> => sdk.fetchJSON(`${BASE}/inbox`),
    requests: (): Promise<{ requests: RequestView[] }> => sdk.fetchJSON(`${BASE}/requests`),
    requestDetail: (requestId: string): Promise<RequestView> =>
      sdk.fetchJSON(`${BASE}/requests/${encodeURIComponent(requestId)}`),
    respond: (requestId: string, action: string, detail?: string): Promise<RequestView> =>
      sdk.fetchJSON(`${BASE}/requests/${encodeURIComponent(requestId)}/respond`, {
        method: 'POST',
        body: JSON.stringify({ action, detail: detail || '' }),
        headers: { 'Content-Type': 'application/json' },
      }),

    /** WebSocket events — uses the host's buildWsUrl for auth. */
    onEvents: (fn: (frame: EventsFrame) => void, onState?: (state: WsState) => void): (() => void) => {
      let ws: WebSocket | null = null;
      let cancelled = false;
      const setState = (s: WsState) => {
        if (cancelled) return;
        if (onState) onState(s);
      };
      sdk.buildWsUrl(`${BASE}/events`).then((url) => {
        if (cancelled) return;
        ws = new WebSocket(url);
        ws.onopen = () => setState('connected');
        ws.onmessage = (e) => {
          if (cancelled) return;
          try { fn(JSON.parse(e.data as string)); } catch { /* ignore malformed frames */ }
        };
        ws.onerror = () => { setState('reconnecting'); /* socket errors are non-fatal; polling is the fallback */ };
        ws.onclose = () => { setState('reconnecting'); /* degraded but alive via polling */ };
      }).catch(() => { setState('reconnecting'); /* buildWsUrl failed; polling is the fallback */ });
      return () => {
        cancelled = true;
        // C7: null the handlers BEFORE close so no queued event re-enters the
        // unmounted app via the stale closures.
        if (ws) {
          ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
          try { ws.close(); } catch { /* ignore */ }
        }
      };
    },
  };
}

export type Api = ReturnType<typeof createApi>;
