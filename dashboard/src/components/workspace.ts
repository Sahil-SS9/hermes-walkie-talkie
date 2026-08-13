/**
 * Main workspace — tabbed content area.
 *
 * Tab switching uses an explicit render callback (passed from app.ts).
 */

import type { AppState } from '../types';
import type { Api } from '../api';

export function renderWorkspace(
  state: AppState,
  api: Api,
  onTabChange?: (tab: AppState['activeTab']) => void,
): HTMLElement {
  const main = document.createElement('main');
  main.className = 'wt-workspace';

  // Tabs
  const tabs = document.createElement('div');
  tabs.className = 'wt-tabs';
  const tabDefs: Array<[AppState['activeTab'], string]> = [
    ['peers', 'Peers'],
    ['groups', 'Groups'],
    ['inbox', 'Inbox'],
    ['requests', 'Requests'],
    ['health', 'Health'],
  ];
  for (const [key, label] of tabDefs) {
    const btn = document.createElement('button');
    btn.className = 'wt-tab';
    if (key === state.activeTab) btn.classList.add('active');
    btn.textContent = label;
    btn.onclick = () => {
      state.activeTab = key;
      // Re-render tabs
      tabs.querySelectorAll('.wt-tab').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      // Use the explicit render callback
      if (onTabChange) onTabChange(key);
    };
    tabs.appendChild(btn);
  }
  main.appendChild(tabs);

  // Body
  const body = document.createElement('div');
  body.className = 'wt-workspace-body';
  main.appendChild(body);

  return main;
}
