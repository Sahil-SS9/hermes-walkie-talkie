/**
 * Shared types for the Walkie-Talkie Dashboard plugin.
 */

import type { PeerView, RequestView, InboxRowView, GroupView, HealthView, SummaryView, WsState } from './api';

export interface AppState {
  loading: boolean;
  error: string | null;
  peers: PeerView[];
  requests: RequestView[];
  inbox: InboxRowView[];
  groups: GroupView[];
  health: HealthView | null;
  summary: SummaryView | null;
  youPeerId: string | null;
  wsState: WsState;
  activeTab: 'peers' | 'groups' | 'inbox' | 'requests' | 'health';
  activeTheme: string;
  lastUpdated: number | null;
  selectedPeer: PeerView | null;
}
