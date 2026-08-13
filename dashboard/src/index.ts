/**
 * Walkie-Talkie Dashboard Plugin — main entry point.
 *
 * Loaded by the Hermes Dashboard host as a standalone tab at /plugins/hermes-peer.
 * The host injects a global `__HERMES_DASHBOARD_API__` with:
 *   - rest<T>(path, opts?) → Promise<T>  (namespace-scoped to /api/plugins/hermes-peer)
 *   - socket(path, onMessage) → () => void
 *   - profile → string
 *
 * Product contract:
 *   - Detailed Walkie-Talkie workspace
 *   - Ember Relay default + 7 persistent local themes
 *   - Transmission icon
 *   - Reachable peer inspector/action popover
 *   - Receipt/request detail modals
 *   - Speech-to-text UI with explicit unavailable fallback
 *   - Control Room as attention/deep-link only
 */

import { initApp } from './app';
import './style.css';

// Wait for DOM + host API
function whenReady(): Promise<void> {
  return new Promise((resolve) => {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => resolve());
    } else {
      resolve();
    }
  });
}

whenReady().then(() => {
  const api = (window as any).__HERMES_DASHBOARD_API__;
  if (!api) {
    document.body.innerHTML = '<div style="padding:2rem;color:var(--danger,#f87171)">Dashboard host API not available. This plugin must be loaded inside the Hermes Dashboard.</div>';
    return;
  }
  initApp(api);
});
