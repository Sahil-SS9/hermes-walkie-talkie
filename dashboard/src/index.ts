/**
 * Walkie-Talkie Dashboard Plugin — main entry point.
 *
 * Loaded by the Hermes Dashboard host as a standalone tab at /plugins/hermes-peer.
 *
 * The host exposes two globals:
 *   window.__HERMES_PLUGIN_SDK__  — React, hooks, fetchJSON, buildWsUrl, utils, etc.
 *   window.__HERMES_PLUGINS__     — .register(name, Component) to register the tab.
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
import type { HermesPluginSDK } from './api';
import './style.css';

// ---------------------------------------------------------------------------
// Resolve the host SDK
// ---------------------------------------------------------------------------

function getSDK(): HermesPluginSDK | null {
  const sdk = (window as any).__HERMES_PLUGIN_SDK__;
  if (!sdk) return null;
  // Quick sanity: the real SDK has fetchJSON and buildWsUrl
  if (typeof sdk.fetchJSON !== 'function' || typeof sdk.buildWsUrl !== 'function') return null;
  return sdk as HermesPluginSDK;
}

// ---------------------------------------------------------------------------
// Register the plugin component with the host loader
// ---------------------------------------------------------------------------

function registerPlugin(sdk: HermesPluginSDK): void {
  const registry = (window as any).__HERMES_PLUGINS__;
  if (!registry || typeof registry.register !== 'function') {
    // Fallback: render directly into #root (dev / standalone mode)
    initApp(sdk);
    return;
  }

  // Register a React component wrapper so the host loader can mount us
  // in the correct tab slot.  We use the SDK's own React to avoid bundling
  // a second copy.
  const { useEffect, useRef } = sdk.hooks;
  const React = sdk.React;

  const WalkieTalkieTab: any = () => {
    const ref = useRef(null);
    useEffect(() => {
      if (ref.current) {
        // Clear any previous content and mount the vanilla-DOM app
        ref.current.innerHTML = '';
        initApp(sdk, ref.current);
      }
    }, []);
    return React.createElement('div', { ref, className: 'wt-dashboard' });
  };

  registry.register('hermes-peer', WalkieTalkieTab);
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

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
  const sdk = getSDK();
  if (!sdk) {
    document.body.innerHTML = '<div style="padding:2rem;color:var(--danger,#f87171)">Dashboard host SDK not available. This plugin must be loaded inside the Hermes Dashboard.</div>';
    return;
  }
  registerPlugin(sdk);
});
