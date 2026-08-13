/**
 * Walkie-Talkie Dashboard — main application shell.
 *
 * Renders the full workspace layout:
 *   - Header (transmission icon, theme picker, profile)
 *   - Control Room attention banner
 *   - Peer rail (left sidebar)
 *   - Main workspace (tabs: Peers, Groups, Inbox, Requests, Health)
 *   - Modals (receipt/request detail)
 *   - Speech-to-text panel
 */

import { createApi, type DashboardHost, type PeerView, type RequestView, type InboxRowView } from './api';
import type { AppState } from './types';
import { applyTheme, getStoredTheme, getThemeById, setStoredTheme } from './theme';
import { renderHeader } from './components/header';
import { renderControlRoom } from './components/control-room';
import { renderPeerRail } from './components/peer-rail';
import { renderWorkspace } from './components/workspace';
import { renderModals } from './components/modals';
import { renderSpeechToText } from './components/speech-to-text';

export function initApp(host: DashboardHost): void {
  const api = createApi(host);

  // Initial theme
  const stored = getStoredTheme();
  applyTheme(getThemeById(stored));

  // State
  const state: AppState = {
    loading: true,
    error: null,
    peers: [],
    requests: [],
    inbox: [],
    groups: [],
    health: null,
    activeTab: 'peers',
    activeTheme: stored,
    lastUpdated: null,
  };

  // Build DOM shell
  const root = document.getElementById('root') || document.body;
  root.innerHTML = '';
  root.className = 'wt-dashboard';

  // Noise overlay
  const noise = document.createElement('div');
  noise.className = 'wt-noise';
  root.appendChild(noise);

  // Shell
  const shell = document.createElement('div');
  shell.className = 'wt-shell';
  root.appendChild(shell);

  // Header
  const header = renderHeader(state, (themeId) => {
    state.activeTheme = themeId;
    setStoredTheme(themeId);
    applyTheme(getThemeById(themeId));
  });
  shell.appendChild(header);

  // Control Room attention
  const controlRoom = renderControlRoom();
  shell.appendChild(controlRoom);

  // Layout
  const layout = document.createElement('div');
  layout.className = 'wt-layout';
  shell.appendChild(layout);

  // Peer rail
  const peerRail = renderPeerRail(state);
  layout.appendChild(peerRail);

  // Main workspace
  const workspace = renderWorkspace(state, api);
  layout.appendChild(workspace);

  // Modals
  const modals = renderModals(api);
  shell.appendChild(modals);

  // Speech-to-text
  const stt = renderSpeechToText();
  shell.appendChild(stt);

  // Refresh function
  async function refresh(): Promise<void> {
    state.loading = true;
    updateUI();
    try {
      const [peersRes, requestsRes, inboxRes, groupsRes, healthRes] = await Promise.all([
        api.peers(),
        api.requests(),
        api.inbox(),
        api.groups(),
        api.health(),
      ]);
      state.peers = peersRes.peers;
      state.requests = requestsRes.requests;
      state.inbox = inboxRes.messages;
      state.groups = groupsRes.groups;
      state.health = healthRes;
      state.error = null;
      state.lastUpdated = Date.now();
    } catch (err: any) {
      state.error = String(err?.message || err);
    }
    state.loading = false;
    updateUI();
  }

  // Wire up events socket
  const offEvents = api.onEvents(() => {
    refresh();
  });

  // Update UI after state changes
  function updateUI(): void {
    // Update peer rail
    const railList = peerRail.querySelector('.wt-peer-list');
    if (railList) {
      railList.innerHTML = '';
      for (const peer of state.peers) {
        railList.appendChild(buildPeerItem(peer));
      }
      const count = peerRail.querySelector('.wt-rail-count');
      if (count) count.textContent = String(state.peers.length);
    }

    // Update workspace
    const body = workspace.querySelector('.wt-workspace-body');
    if (body) {
      body.innerHTML = '';
      if (state.loading) {
        body.innerHTML = '<div class="wt-muted">Loading…</div>';
      } else if (state.error) {
        body.innerHTML = `<div class="wt-error">${escapeHtml(state.error)}</div>`;
      } else {
        body.appendChild(buildTabContent(state, api));
      }
    }

    // Update control room
    const crCount = controlRoom.querySelector('.wt-cr-count');
    if (crCount) {
      const held = state.inbox.filter((m) => m.state === 'held').length;
      const pending = state.requests.filter((r) => r.state === 'pending').length;
      const total = held + pending;
      crCount.textContent = String(total);
      controlRoom.style.display = total > 0 ? '' : 'none';
    }
  }

  // Initial load
  refresh();

  // Cleanup on unload
  window.addEventListener('beforeunload', () => {
    offEvents();
  });
}

function buildPeerItem(peer: PeerView): HTMLElement {
  const li = document.createElement('li');
  li.className = 'wt-peer-item';
  li.setAttribute('data-peer', peer.name || peer.agent_id);
  li.setAttribute('data-meta', `${peer.surface} · ${peer.status} · ${peer.profile || 'default'}`);

  const avatar = document.createElement('div');
  avatar.className = 'wt-peer-avatar';
  avatar.textContent = (peer.name || peer.agent_id).charAt(0).toUpperCase();

  const info = document.createElement('div');
  info.className = 'wt-peer-info';
  info.innerHTML = `<b>${escapeHtml(peer.name || peer.agent_id.slice(0, 8))}</b><small>${escapeHtml(peer.surface)} · ${escapeHtml(peer.status)}</small>`;

  const presence = document.createElement('i');
  presence.className = 'wt-presence';
  if (peer.status === 'active') presence.classList.add('active');

  li.appendChild(avatar);
  li.appendChild(info);
  li.appendChild(presence);

  // Hover inspector
  li.addEventListener('mouseenter', () => {
    const inspector = document.getElementById('wt-inspector');
    if (!inspector) return;
    const nameEl = document.getElementById('wt-inspect-name');
    const bodyEl = document.getElementById('wt-inspect-body');
    if (nameEl) nameEl.textContent = peer.name || peer.agent_id;
    if (bodyEl) bodyEl.textContent = `${peer.surface} session. ${peer.status}. Profile: ${peer.profile || 'default'}. CWD: ${peer.cwd}`;
    const rect = li.getBoundingClientRect();
    inspector.style.left = `${rect.right + 12}px`;
    inspector.style.top = `${Math.max(86, rect.top - 4)}px`;
    inspector.classList.add('show');
  });
  li.addEventListener('mouseleave', () => {
    const inspector = document.getElementById('wt-inspector');
    if (inspector) setTimeout(() => inspector.classList.remove('show'), 220);
  });

  return li;
}

function buildTabContent(state: AppState, api: ReturnType<typeof createApi>): HTMLElement {
  const div = document.createElement('div');
  switch (state.activeTab) {
    case 'peers':
      div.appendChild(buildPeersTab(state));
      break;
    case 'groups':
      div.appendChild(buildGroupsTab(state, api));
      break;
    case 'inbox':
      div.appendChild(buildInboxTab(state));
      break;
    case 'requests':
      div.appendChild(buildRequestsTab(state));
      break;
    case 'health':
      div.appendChild(buildHealthTab(state));
      break;
  }
  return div;
}

function buildPeersTab(state: AppState): HTMLElement {
  const div = document.createElement('div');
  if (!state.peers.length) {
    div.innerHTML = '<div class="wt-muted">No live peers.</div>';
    return div;
  }
  const table = document.createElement('table');
  table.className = 'wt-table';
  table.innerHTML = `<thead><tr><th>Name</th><th>Agent ID</th><th>Surface</th><th>Status</th><th>Profile</th><th>Branch</th></tr></thead>`;
  const tbody = document.createElement('tbody');
  for (const p of state.peers) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><strong>${escapeHtml(p.name || '—')}</strong></td><td><code>${escapeHtml(p.agent_id.slice(0, 12))}</code></td><td>${escapeHtml(p.surface)}</td><td><span class="wt-badge wt-badge-${p.status}">${escapeHtml(p.status)}</span></td><td>${escapeHtml(p.profile || 'default')}</td><td>${escapeHtml(p.git_branch || '—')}</td>`;
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  div.appendChild(table);
  return div;
}

function buildGroupsTab(state: AppState, api: ReturnType<typeof createApi>): HTMLElement {
  const div = document.createElement('div');

  // Create group form
  const form = document.createElement('div');
  form.className = 'wt-form';
  const input = document.createElement('input');
  input.placeholder = 'Group name';
  input.setAttribute('aria-label', 'New group name');
  const btn = document.createElement('button');
  btn.textContent = 'Create';
  btn.onclick = async () => {
    const name = input.value.trim();
    if (!name) return;
    try {
      await api.createGroup(name);
      input.value = '';
      // Refresh groups
      const res = await api.groups();
      state.groups = res.groups;
      updateGroupList(list, state);
    } catch (err: any) {
      alert('Failed to create group: ' + (err?.message || err));
    }
  };
  form.appendChild(input);
  form.appendChild(btn);
  div.appendChild(form);

  const list = document.createElement('ul');
  list.className = 'wt-list';
  updateGroupList(list, state);
  div.appendChild(list);

  return div;
}

function updateGroupList(list: HTMLElement, state: AppState): void {
  list.innerHTML = '';
  if (!state.groups.length) {
    list.innerHTML = '<li class="wt-muted">No groups.</li>';
    return;
  }
  for (const g of state.groups) {
    const li = document.createElement('li');
    li.className = 'wt-row';
    li.innerHTML = `<span class="wt-row-title">${escapeHtml(g.name)}</span><span class="wt-row-meta">${g.members} members</span>`;
    list.appendChild(li);
  }
}

function buildInboxTab(state: AppState): HTMLElement {
  const div = document.createElement('div');
  if (!state.inbox.length) {
    div.innerHTML = '<div class="wt-muted">Inbox empty.</div>';
    return div;
  }
  const list = document.createElement('ul');
  list.className = 'wt-list';
  for (const m of state.inbox) {
    const li = document.createElement('li');
    li.className = 'wt-row receipt-trigger';
    li.setAttribute('data-message-id', m.message_id);
    li.setAttribute('data-state', m.state);
    li.setAttribute('data-content', m.content);
    li.setAttribute('data-sender', m.sender_peer_id);
    li.innerHTML = `<span class="wt-row-title">[${escapeHtml(m.state)}]</span><span class="wt-row-meta">${escapeHtml(m.content.slice(0, 80))}</span>`;
    li.onclick = () => openReceiptModal(m);
    div.appendChild(li);
  }
  list.appendChild(div.firstChild!);
  return list;
}

function buildRequestsTab(state: AppState): HTMLElement {
  const div = document.createElement('div');
  if (!state.requests.length) {
    div.innerHTML = '<div class="wt-muted">No requests.</div>';
    return div;
  }
  const list = document.createElement('ul');
  list.className = 'wt-list';
  for (const r of state.requests) {
    const li = document.createElement('li');
    li.className = 'wt-row request-trigger';
    li.setAttribute('data-request-id', r.request_id);
    li.innerHTML = `<span class="wt-row-title">[${escapeHtml(r.state)}]</span><span class="wt-row-meta">${escapeHtml(r.summary)}</span><span class="wt-row-meta">${escapeHtml(r.created_at || '')}</span>`;
    li.onclick = () => openRequestModal(r);
    list.appendChild(li);
  }
  div.appendChild(list);
  return div;
}

function buildHealthTab(state: AppState): HTMLElement {
  const div = document.createElement('div');
  if (!state.health) {
    div.innerHTML = '<div class="wt-muted">Checking…</div>';
    return div;
  }
  const h = state.health;
  div.innerHTML = `
    <div class="wt-health-summary">
      <span class="wt-badge ${h.ok ? 'wt-badge-active' : 'wt-badge-error'}">${h.ok ? 'Healthy' : 'Unhealthy'}</span>
      <span>Backend: ${escapeHtml(h.backend)}</span>
      <span>Live peers: ${h.live_peers}</span>
      <span>Pending: ${h.pending_messages}</span>
      <span>Held: ${h.held_messages}</span>
    </div>
  `;
  if (h.problems.length) {
    const list = document.createElement('ul');
    list.className = 'wt-list';
    for (const p of h.problems) {
      const li = document.createElement('li');
      li.className = 'wt-row';
      li.innerHTML = `<span class="wt-row-title">[${escapeHtml(p.severity)}] ${escapeHtml(p.problem)}</span><span class="wt-row-meta">${escapeHtml(p.remedy)}</span>`;
      list.appendChild(li);
    }
    div.appendChild(list);
  }
  return div;
}

function openReceiptModal(msg: InboxRowView): void {
  const overlay = document.getElementById('wt-overlay');
  const title = document.getElementById('wt-modal-title');
  const body = document.getElementById('wt-modal-body');
  if (!overlay || !title || !body) return;
  title.textContent = `Receipt: ${msg.message_id.slice(0, 12)}`;
  body.innerHTML = `
    <div class="wt-modal-field"><label>State</label><span class="wt-badge wt-badge-${msg.state}">${escapeHtml(msg.state)}</span></div>
    <div class="wt-modal-field"><label>Sender</label><span>${escapeHtml(msg.sender_peer_id)}</span></div>
    <div class="wt-modal-field"><label>Content</label><pre>${escapeHtml(msg.content)}</pre></div>
  `;
  overlay.classList.add('show');
}

function openRequestModal(req: RequestView): void {
  const overlay = document.getElementById('wt-overlay');
  const title = document.getElementById('wt-modal-title');
  const body = document.getElementById('wt-modal-body');
  if (!overlay || !title || !body) return;
  title.textContent = `Request: ${req.request_id.slice(0, 12)}`;
  body.innerHTML = `
    <div class="wt-modal-field"><label>State</label><span class="wt-badge wt-badge-${req.state}">${escapeHtml(req.state)}</span></div>
    <div class="wt-modal-field"><label>Sender</label><span>${escapeHtml(req.sender_agent_id)}</span></div>
    <div class="wt-modal-field"><label>Summary</label><p>${escapeHtml(req.summary)}</p></div>
    <div class="wt-modal-field"><label>Created</label><span>${escapeHtml(req.created_at || '—')}</span></div>
    <div class="wt-modal-field"><label>Deadline</label><span>${escapeHtml(req.deadline || 'None')}</span></div>
  `;
  overlay.classList.add('show');
}

function escapeHtml(s: string): string {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
