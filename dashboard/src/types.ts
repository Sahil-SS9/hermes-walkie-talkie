/**
 * Shared types for the Walkie-Talkie Dashboard plugin.
 */

import type { PeerView, RequestView, InboxRowView, GroupView, HealthView } from './api';

export interface AppState {
  loading: boolean;
  error: string | null;
  peers: PeerView[];
  requests: RequestView[];
  inbox: InboxRowView[];
  groups: GroupView[];
  health: HealthView | null;
  activeTab: 'peers' | 'groups' | 'inbox' | 'requests' | 'health';
  activeTheme: string;
  lastUpdated: number | null;
  selectedPeer: PeerView | null;
}
