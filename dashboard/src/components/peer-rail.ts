/**
 * Peer rail — left sidebar listing live sessions.
 * Each peer has hover inspector + click action popover.
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

  // Peer inspector popover
  const inspector = document.createElement('div');
  inspector.className = 'wt-inspector';
  inspector.id = 'wt-inspector';
  inspector.innerHTML = `
    <div class="wt-inspect-name" id="wt-inspect-name"></div>
    <div class="wt-inspect-body" id="wt-inspect-body"></div>
  `;
  inspector.addEventListener('mouseenter', () => {
    // Keep inspector open when hovering it
  });
  inspector.addEventListener('mouseleave', () => {
    inspector.classList.remove('show');
  });
  aside.appendChild(inspector);

  return aside;
}
