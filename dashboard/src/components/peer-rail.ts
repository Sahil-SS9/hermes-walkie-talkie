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
  aside.appendChild(list);

  // Peer inspector popover with action buttons
  const inspector = document.createElement('div');
  inspector.className = 'wt-inspector';
  inspector.id = 'wt-inspector';
  inspector.setAttribute('tabindex', '0');
  inspector.setAttribute('role', 'tooltip');
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
  inspector.addEventListener('mouseenter', () => {
    // Keep inspector open when hovering it
  });
  inspector.addEventListener('mouseleave', () => {
    inspector.classList.remove('show');
  });
  // Keyboard: hide on Escape
  inspector.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      inspector.classList.remove('show');
    }
  });
  aside.appendChild(inspector);

  return aside;
}
