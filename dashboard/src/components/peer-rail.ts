/**
 * Peer rail — left sidebar listing live sessions.
 * Each peer has hover inspector + action popover with Copy agent ID and Focus peer buttons.
 */

import type { AppState } from '../types';

export function renderPeerRail(state: AppState): HTMLElement {
  const aside = document.createElement('aside');
  aside.className = 'wt-rail';

  const eyebrow = document.createElement('div');
  eyebrow.className = 'wt-eyebrow';
  eyebrow.innerHTML = `Live sessions · <span class="wt-rail-count">${state.peers.length}</span>`;
  aside.appendChild(eyebrow);

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
