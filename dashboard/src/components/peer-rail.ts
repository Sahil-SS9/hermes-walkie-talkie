/**
 * Peer rail — left sidebar listing live sessions.
 * Each peer has hover inspector + action popover with Copy agent ID and Focus peer buttons.
 *
 * Presence remediation (G2/G5/G6): the eyebrow now carries the active
 * count (`Live sessions · N · M active`), a liveness line (`● Live ·
 * updated 2s ago`, `.live.off` when reconnecting) and the rail exposes
 * the mockup class vocabulary (.dot.g/.a/.q/.r, .item.me/.off/.sel,
 * .you pill, .act line).
 */

import type { AppState } from '../types';
import type { WsState } from '../api';

/** Human "N seconds/minutes ago" stamp from an RFC3339 UTC timestamp. */
export function timeAgoFromIso(iso: string, now: number = Date.now()): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 2) return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

/** Live-pill copy per WS state (G5): connected = ● Live, else ○ reconnecting. */
export function liveLabel(wsState: WsState, lastUpdated: number | null, summaryUpdated: string): string {
  if (wsState === 'reconnecting' || wsState === 'closed') return '○ reconnecting';
  if (wsState === 'connecting') return '● Live · connecting…';
  if (lastUpdated != null && summaryUpdated) return `● Live · updated ${timeAgoFromIso(summaryUpdated)}`;
  if (lastUpdated != null) return '● Live · updated just now';
  return '● Live';
}

/** S7: single offline-lookup helper (was repeated 4× across app.ts/PeerPanel). */
export function isPeerOffline(state: AppState, peerId: string): boolean {
  return offlineSet(state).has(peerId);
}

/** R7: build a Set<peer_id> of offline peers ONCE per render — O(N) total
 *  instead of O(N²) per-peer `.some()` scans on every WS refresh. */
export function offlineSet(state: AppState): Set<string> {
  const peers = state.summary?.peers || [];
  const set = new Set<string>();
  for (const p of peers) {
    if (p.offline) set.add(p.peer_id);
  }
  return set;
}

/** S8: single eyebrow renderer used by both renderPeerRail and updateUI. */
export function renderEyebrow(state: AppState): string {
  const s = state.summary;
  const live = s ? (s as { live_count?: number }).live_count ?? 0 : 0;
  const active = s ? s.active_count : 0;
  const idle = s ? (s as { idle_count?: number }).idle_count ?? 0 : 0;
  const offline = s ? s.offline_count : 0;
  let out = `Live sessions · <span class="wt-rail-count">${live}</span>`;
  if (s) {
    if (active > 0 && active < live) out += ` &nbsp; <b class="wt-rail-active">${active} working</b>`;
    if (idle > 0) out += ` &nbsp; <span class="wt-rail-idle">${idle} idle</span>`;
    if (offline > 0) out += ` &nbsp; <span class="wt-rail-off">${offline} off</span>`;
  }
  return out;
}

export function renderPeerRail(state: AppState): HTMLElement {
  const aside = document.createElement('aside');
  aside.className = 'wt-rail';

  const eyebrow = document.createElement('div');
  eyebrow.className = 'wt-eyebrow';
  eyebrow.id = 'wt-eyebrow';
  eyebrow.innerHTML = renderEyebrow(state);
  aside.appendChild(eyebrow);

  // Liveness line (G5): `● Live · updated 2s ago`, `.off` when reconnecting.
  const live = document.createElement('div');
  live.className = 'wt-live';
  live.id = 'wt-live';
  live.textContent = liveLabel(state.wsState, state.lastUpdated, state.summary?.last_updated || '');
  if (state.wsState === 'reconnecting' || state.wsState === 'closed') live.classList.add('off');
  aside.appendChild(live);

  const list = document.createElement('ul');
  list.className = 'wt-peer-list';
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', 'Live peer sessions');
  aside.appendChild(list);

  // Peer inspector popover with action buttons
  // Uses role="dialog" (interactive popover), NOT role="tooltip" (which forbids buttons)
  const inspector = document.createElement('div');
  inspector.className = 'wt-inspector';
  inspector.id = 'wt-inspector';
  inspector.setAttribute('tabindex', '0');
  inspector.setAttribute('role', 'dialog');
  inspector.setAttribute('aria-label', 'Peer inspector');
  inspector.innerHTML = `
    <div class="wt-inspect-name" id="wt-inspect-name"></div>
    <div class="wt-inspect-body" id="wt-inspect-body"></div>
    <div class="wt-inspect-actions" id="wt-inspect-actions">
      <button class="wt-btn wt-inspect-action" id="wt-action-copy" title="Copy agent ID to clipboard" aria-label="Copy agent ID">
        <span class="wt-action-icon">📋</span> Copy agent ID
      </button>
      <button class="wt-btn wt-inspect-action" id="wt-action-focus" title="Focus this peer" aria-label="Focus peer">
        <span class="wt-action-icon">🔍</span> Focus peer
      </button>
    </div>
  `;

  // Inspector listeners are attached ONCE here (not per buildPeerItem).
  // The mouseenter/mouseleave on the inspector itself are handled in app.ts
  // at init time, not duplicated here.
  aside.appendChild(inspector);

  return aside;
}
