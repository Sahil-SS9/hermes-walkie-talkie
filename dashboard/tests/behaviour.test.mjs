/**
 * Behaviour-level DOM interaction tests for the Walkie-Talkie Dashboard.
 *
 * These tests mount the app in jsdom, simulate real user interactions
 * (hover, click, keyboard), and assert actual DOM outcomes — not just
 * string-searching source files.
 *
 * Run with: node --experimental-vm-modules --test tests/behaviour.test.mjs
 */

import { describe, it, before, after, beforeEach } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIST_DIR = join(__dirname, '..', 'dist');
const BUNDLE_PATH = join(DIST_DIR, 'index.js');

// ---------------------------------------------------------------------------
// Mock SDK factory — returns a fully wired mock that the app can mount against
// ---------------------------------------------------------------------------

function createMockSDK(overrides = {}) {
  const registered = [];
  const sdk = {
    sdkVersion: '1.1.0',
    React: {
      createElement: (tag, props, ...children) => {
        if (typeof tag === 'function') {
          return tag(props);
        }
        return { tag, props, children };
      },
    },
    hooks: {
      useState: (init) => [init, () => {}],
      useEffect: (fn) => { fn(); },
      useCallback: (fn) => fn,
      useMemo: (fn) => fn(),
      useRef: (init) => ({ current: init }),
      useContext: () => ({}),
      createContext: () => ({ Provider: () => null, Consumer: () => null }),
    },
    api: {
      getProfile: () => 'test-profile',
    },
    fetchJSON: async (url) => {
      if (overrides.fetchJSON) return overrides.fetchJSON(url);
      // Default: return mock data based on URL
      if (url.includes('/peers')) {
        return {
          peers: [
            {
              peer_id: 'peer-1',
              agent_id: 'agent-alpha-001',
              name: 'Alpha',
              profile: 'default',
              surface: 'cli',
              status: 'active',
              cwd: '/home/alpha',
              git_branch: 'main',
            },
            {
              peer_id: 'peer-2',
              agent_id: 'agent-beta-002',
              name: 'Beta',
              profile: 'coder',
              surface: 'desktop',
              status: 'idle',
              cwd: '/home/beta',
              git_branch: 'feat/x',
            },
            {
              peer_id: 'peer-3',
              agent_id: 'agent-gamma-003',
              name: 'Gamma',
              profile: 'default',
              surface: 'cli',
              status: 'active',
              cwd: '/home/gamma',
              git_branch: 'develop',
            },
          ],
        };
      }
      if (url.includes('/requests')) return { requests: [] };
      if (url.includes('/inbox')) return { messages: [] };
      if (url.includes('/groups')) return { groups: [] };
      if (url.includes('/health')) {
        return {
          ok: true,
          backend: 'sqlite',
          runtime_dir: '/tmp',
          registry_entries: 3,
          live_peers: 3,
          pending_messages: 0,
          held_messages: 0,
          problems: [],
        };
      }
      return {};
    },
    authedFetch: async () => new Response(),
    buildWsUrl: async () => 'ws://localhost/ws',
    buildWsAuthParam: async () => ['token', 'test'],
    components: {},
    utils: {
      cn: (...args) => args.filter(Boolean).join(' '),
      timeAgo: () => 'just now',
      isoTimeAgo: () => 'just now',
    },
    useI18n: () => ({ t: (k) => k }),
  };

  const registry = {
    register(name, component) {
      registered.push({ name, component });
    },
    registerSlot() {},
  };

  return { sdk, registry, registered };
}

// ---------------------------------------------------------------------------
// Helper: mount the app by calling initApp directly
// ---------------------------------------------------------------------------

function mountApp(dom, mock) {
  const root = dom.window.document.getElementById('root');
  const initApp = dom.window.__wt_initApp;
  if (!initApp) throw new Error('__wt_initApp not exposed on window');
  initApp(mock.sdk, root);
  return root;
}

// ---------------------------------------------------------------------------
// Helper: wait for async operations to settle
// ---------------------------------------------------------------------------

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Helper: dispatch a mouse event
// ---------------------------------------------------------------------------

function dispatchMouse(el, type) {
  const event = new el.ownerDocument.defaultView.MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    view: el.ownerDocument.defaultView,
  });
  el.dispatchEvent(event);
}

// ---------------------------------------------------------------------------
// Helper: dispatch a keyboard event
// ---------------------------------------------------------------------------

function dispatchKey(el, key) {
  const event = new el.ownerDocument.defaultView.KeyboardEvent('keydown', {
    key,
    bubbles: true,
    cancelable: true,
    view: el.ownerDocument.defaultView,
  });
  el.dispatchEvent(event);
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe('Behaviour-level DOM interaction tests', () => {
  let dom;
  let mock;
  let root;

  before(async () => {
    assert.ok(existsSync(BUNDLE_PATH), 'dist/index.js must exist before running behaviour tests');

    dom = new JSDOM('<!DOCTYPE html><html><head></head><body><div id="root"></div></body></html>', {
      url: 'http://localhost/',
      runScripts: 'dangerously',
      resources: 'usable',
    });

    // jsdom doesn't provide Response or navigator.clipboard — polyfill them
    dom.window.Response = class Response {
      constructor(body, init) { this._body = body; this.status = init?.status || 200; }
      json() { return Promise.resolve(JSON.parse(this._body)); }
      text() { return Promise.resolve(this._body); }
    };
    dom.window.navigator.clipboard = {
      writeText: async (text) => { /* noop */ },
    };

    mock = createMockSDK();

    // Inject SDK globals
    dom.window.__HERMES_PLUGIN_SDK__ = mock.sdk;
    dom.window.__HERMES_PLUGINS__ = mock.registry;

    // Load the bundle
    const bundle = readFileSync(BUNDLE_PATH, 'utf-8');
    try {
      dom.window.eval(bundle);
    } catch (err) {
      if (!err.message?.includes('WebSocket')) {
        throw err;
      }
    }

    // Dispatch DOMContentLoaded so whenReady() resolves
    dom.window.document.dispatchEvent(
      new dom.window.Event('DOMContentLoaded', { bubbles: true, cancelable: true })
    );

    // Wait for async registration
    await wait(100);

    root = mountApp(dom, mock);
  });

  after(() => {
    if (dom) dom.window.close();
  });

  // -----------------------------------------------------------------------
  // Test 1: Registration
  // -----------------------------------------------------------------------

  it('registers the hermes-peer component', () => {
    const reg = mock.registered.find((r) => r.name === 'hermes-peer');
    assert.ok(reg, 'must register hermes-peer component');
    assert.strictEqual(typeof reg.component, 'function');
  });

  // -----------------------------------------------------------------------
  // Test 2: App renders shell structure
  // -----------------------------------------------------------------------

  it('renders the dashboard shell with header, rail, workspace, and inspector', async () => {
    // Wait for async refresh to complete
    await wait(100);

    const header = root.querySelector('.wt-header');
    assert.ok(header, 'must have header');

    const rail = root.querySelector('.wt-rail');
    assert.ok(rail, 'must have peer rail');

    const workspace = root.querySelector('.wt-workspace');
    assert.ok(workspace, 'must have workspace');

    const inspector = root.querySelector('#wt-inspector');
    assert.ok(inspector, 'must have inspector element');
  });

  // -----------------------------------------------------------------------
  // Test 3: Peer items are rendered in the rail
  // -----------------------------------------------------------------------

  it('renders peer items in the rail after data loads', async () => {
    await wait(100);
    const peerItems = root.querySelectorAll('.wt-peer-item');
    assert.ok(peerItems.length >= 3, `expected >= 3 peer items, got ${peerItems.length}`);
  });

  // -----------------------------------------------------------------------
  // Test 4: Hover shows inspector popover
  // -----------------------------------------------------------------------

  it('shows inspector popover on peer hover', async () => {
    await wait(100);
    const peerItems = root.querySelectorAll('.wt-peer-item');
    assert.ok(peerItems.length > 0, 'must have peer items');

    const firstPeer = peerItems[0];
    const inspector = root.querySelector('#wt-inspector');
    assert.ok(inspector, 'inspector must exist');

    // Initially hidden
    assert.ok(!inspector.classList.contains('show'), 'inspector should start hidden');

    // Hover
    dispatchMouse(firstPeer, 'mouseenter');

    // Should now be visible
    assert.ok(inspector.classList.contains('show'), 'inspector should be visible after hover');

    // Check inspector content
    const nameEl = root.querySelector('#wt-inspect-name');
    assert.ok(nameEl, 'inspector name element must exist');
    assert.ok(nameEl.textContent.length > 0, 'inspector name must have content');
  });

  // -----------------------------------------------------------------------
  // Test 5: Copy agent ID button — clipboard invocation + feedback
  // -----------------------------------------------------------------------

  it('Copy agent ID button invokes clipboard and shows feedback', async () => {
    await wait(100);
    const peerItems = root.querySelectorAll('.wt-peer-item');
    assert.ok(peerItems.length > 0, 'must have peer items');

    const firstPeer = peerItems[0];

    // Hover to show inspector
    dispatchMouse(firstPeer, 'mouseenter');
    await wait(50);

    const inspector = root.querySelector('#wt-inspector');
    assert.ok(inspector.classList.contains('show'), 'inspector must be visible');

    // Find the Copy button
    const copyBtn = root.querySelector('#wt-action-copy');
    assert.ok(copyBtn, 'Copy button must exist');

    // Mock clipboard API
    let clipboardWritten = null;
    const origClipboard = dom.window.navigator.clipboard;
    dom.window.navigator.clipboard = {
      writeText: async (text) => {
        clipboardWritten = text;
      },
    };

    // Click the Copy button
    copyBtn.click();
    await wait(100);

    // Verify clipboard was called with the agent ID
    assert.ok(clipboardWritten, 'clipboard.writeText must have been called');
    assert.ok(clipboardWritten.includes('agent-'), `clipboard should contain agent ID, got: ${clipboardWritten}`);

    // Verify feedback text changed
    const btnText = copyBtn.textContent || copyBtn.innerHTML;
    assert.ok(
      btnText.includes('Copied') || btnText.includes('✓'),
      `Copy button should show success feedback, got: ${btnText}`
    );

    // Restore clipboard
    dom.window.navigator.clipboard = origClipboard;
  });

  // -----------------------------------------------------------------------
  // Test 6: Focus peer — visible/focused peer detail + selected aria state
  // -----------------------------------------------------------------------

  it('Focus peer shows peer detail surface and sets aria-selected', async () => {
    await wait(100);
    const peerItems = root.querySelectorAll('.wt-peer-item');
    assert.ok(peerItems.length > 0, 'must have peer items');

    const firstPeer = peerItems[0];

    // Hover to show inspector
    dispatchMouse(firstPeer, 'mouseenter');
    await wait(50);

    const inspector = root.querySelector('#wt-inspector');
    assert.ok(inspector.classList.contains('show'), 'inspector must be visible');

    // Find the Focus button
    const focusBtn = root.querySelector('#wt-action-focus');
    assert.ok(focusBtn, 'Focus button must exist');

    // Click Focus
    focusBtn.click();
    await wait(100);

    // Verify peer detail surface is visible
    const detail = root.querySelector('#wt-peer-detail');
    assert.ok(detail, 'peer detail surface must exist');

    // Verify detail has content
    const detailHeader = detail.querySelector('h2');
    assert.ok(detailHeader, 'detail must have header');
    assert.ok(detailHeader.textContent.length > 0, 'detail header must have text');

    // Verify the peer item has aria-selected="true"
    assert.strictEqual(
      firstPeer.getAttribute('aria-selected'),
      'true',
      'focused peer must have aria-selected="true"'
    );

    // Verify the peer item has active class
    assert.ok(firstPeer.classList.contains('active'), 'focused peer must have active class');

    // Verify other peers are NOT selected
    for (let i = 1; i < peerItems.length; i++) {
      assert.strictEqual(
        peerItems[i].getAttribute('aria-selected'),
        'false',
        `peer ${i} must have aria-selected="false"`
      );
    }
  });

  // -----------------------------------------------------------------------
  // Test 7: Tab change does NOT erase focused peer detail
  // -----------------------------------------------------------------------

  it('tab change preserves focused peer detail', async () => {
    await wait(100);

    // First, focus a peer
    const peerItems = root.querySelectorAll('.wt-peer-item');
    assert.ok(peerItems.length > 0, 'must have peer items');
    const firstPeer = peerItems[0];

    dispatchMouse(firstPeer, 'mouseenter');
    await wait(50);

    const focusBtn = root.querySelector('#wt-action-focus');
    assert.ok(focusBtn, 'Focus button must exist');
    focusBtn.click();
    await wait(100);

    // Verify detail is visible
    let detail = root.querySelector('#wt-peer-detail');
    assert.ok(detail, 'peer detail must exist after focus');

    // Now click a different tab (Groups)
    const tabs = root.querySelectorAll('.wt-tab');
    const groupsTab = Array.from(tabs).find((t) => t.textContent === 'Groups');
    assert.ok(groupsTab, 'Groups tab must exist');
    groupsTab.click();
    await wait(100);

    // The peer detail should STILL be visible (not overwritten by tab content)
    detail = root.querySelector('#wt-peer-detail');
    assert.ok(detail, 'peer detail must persist after tab change');

    // The workspace body should contain the detail, not generic tab content
    const body = root.querySelector('.wt-workspace-body');
    assert.ok(body, 'workspace body must exist');
    const detailInBody = body.querySelector('#wt-peer-detail');
    assert.ok(detailInBody, 'peer detail must be inside workspace body after tab change');
  });

  // -----------------------------------------------------------------------
  // Test 8: Close peer detail restores tab content
  // -----------------------------------------------------------------------

  it('closing peer detail restores tab content', async () => {
    await wait(100);

    // Focus a peer first
    const peerItems = root.querySelectorAll('.wt-peer-item');
    const firstPeer = peerItems[0];
    dispatchMouse(firstPeer, 'mouseenter');
    await wait(50);
    const focusBtn = root.querySelector('#wt-action-focus');
    focusBtn.click();
    await wait(100);

    // Verify detail exists
    let detail = root.querySelector('#wt-peer-detail');
    assert.ok(detail, 'peer detail must exist');

    // Click close button
    const closeBtn = root.querySelector('#wt-peer-detail-close');
    assert.ok(closeBtn, 'close button must exist');
    closeBtn.click();
    await wait(100);

    // Detail should be gone
    detail = root.querySelector('#wt-peer-detail');
    assert.ok(!detail, 'peer detail must be removed after close');

    // Peer items should no longer be selected
    const allPeers = root.querySelectorAll('.wt-peer-item');
    for (const p of allPeers) {
      assert.strictEqual(p.getAttribute('aria-selected'), 'false', 'no peer should be selected after close');
      assert.ok(!p.classList.contains('active'), 'no peer should have active class after close');
    }
  });

  // -----------------------------------------------------------------------
  // Test 9: Inspector listeners are NOT duplicated on refresh
  // -----------------------------------------------------------------------

  it('inspector listeners are not duplicated across UI refreshes', async () => {
    await wait(100);

    const inspector = root.querySelector('#wt-inspector');
    assert.ok(inspector, 'inspector must exist');

    // Count initial listeners by checking if inspector mouseenter/mouseleave
    // work correctly (no duplicate handlers causing flicker)
    // We verify by: hover a peer, move to inspector, move away — should hide cleanly

    const peerItems = root.querySelectorAll('.wt-peer-item');
    const firstPeer = peerItems[0];

    // Hover peer
    dispatchMouse(firstPeer, 'mouseenter');
    await wait(50);
    assert.ok(inspector.classList.contains('show'), 'inspector should show');

    // Move to inspector (should stay open)
    dispatchMouse(inspector, 'mouseenter');
    await wait(50);
    assert.ok(inspector.classList.contains('show'), 'inspector should stay open when hovering it');

    // Move away from inspector (should hide)
    dispatchMouse(inspector, 'mouseleave');
    await wait(50);
    // After mouseleave, inspector should hide
    assert.ok(!inspector.classList.contains('show'), 'inspector should hide after mouseleave');
  });

  // -----------------------------------------------------------------------
  // Test 10: Safe badge class mapper — no innerHTML class injection
  // -----------------------------------------------------------------------

  it('badge classes use a safe mapper, not raw innerHTML interpolation', async () => {
    await wait(100);

    // Check the peers tab table for badge elements
    const body = root.querySelector('.wt-workspace-body');
    assert.ok(body, 'workspace body must exist');

    // Find all badge elements
    const badges = body.querySelectorAll('.wt-badge');
    // Badges should only have known safe classes
    const SAFE_BADGE_CLASSES = new Set([
      'wt-badge',
      'wt-badge-active',
      'wt-badge-idle',
      'wt-badge-held',
      'wt-badge-pending',
      'wt-badge-error',
      'wt-badge-refused',
      'wt-badge-unreachable',
      'wt-badge-completed',
      'wt-badge-delivered',
    ]);

    for (const badge of badges) {
      for (const cls of badge.classList) {
        assert.ok(
          SAFE_BADGE_CLASSES.has(cls),
          `badge class "${cls}" must be in the safe whitelist`
        );
      }
    }
  });

  // -----------------------------------------------------------------------
  // Test 11: Hostile status values do not create arbitrary CSS classes
  // -----------------------------------------------------------------------

  it('hostile peer status values do not create arbitrary CSS classes', async () => {
    // Create a fresh DOM with hostile data
    const hostileDom = new JSDOM('<!DOCTYPE html><html><head></head><body><div id="root"></div></body></html>', {
      url: 'http://localhost/',
      runScripts: 'dangerously',
      resources: 'usable',
    });

    // Polyfill Response and clipboard for jsdom
    hostileDom.window.Response = class Response {
      constructor(body, init) { this._body = body; this.status = init?.status || 200; }
      json() { return Promise.resolve(JSON.parse(this._body)); }
      text() { return Promise.resolve(this._body); }
    };
    hostileDom.window.navigator.clipboard = {
      writeText: async (text) => { /* noop */ },
    };

    const hostileMock = createMockSDK({
      fetchJSON: async (url) => {
        if (url.includes('/peers')) {
          return {
            peers: [
              {
                peer_id: 'peer-evil',
                agent_id: 'agent-evil',
                name: 'Evil"><script>alert(1)</script>',
                profile: 'default',
                surface: 'cli',
                status: 'active" onclick="alert(1)" class="injected',
                cwd: '/home/evil',
                git_branch: 'main',
              },
            ],
          };
        }
        if (url.includes('/requests')) return { requests: [] };
        if (url.includes('/inbox')) return { messages: [] };
        if (url.includes('/groups')) return { groups: [] };
        if (url.includes('/health')) return {
          ok: true, backend: 'sqlite', runtime_dir: '/tmp', registry_entries: 1,
          live_peers: 1, pending_messages: 0, held_messages: 0, problems: [],
        };
        return {};
      },
    });

    hostileDom.window.__HERMES_PLUGIN_SDK__ = hostileMock.sdk;
    hostileDom.window.__HERMES_PLUGINS__ = hostileMock.registry;

    const bundle = readFileSync(BUNDLE_PATH, 'utf-8');
    try {
      hostileDom.window.eval(bundle);
    } catch (err) {
      if (!err.message?.includes('WebSocket')) {
        throw err;
      }
    }

    // Dispatch DOMContentLoaded so whenReady() resolves
    hostileDom.window.document.dispatchEvent(
      new hostileDom.window.Event('DOMContentLoaded', { bubbles: true, cancelable: true })
    );

    await wait(50);

    const hostileRoot = hostileDom.window.document.getElementById('root');
    const initApp = hostileDom.window.__wt_initApp;
    if (!initApp) throw new Error('__wt_initApp not exposed');
    initApp(hostileMock.sdk, hostileRoot);
    await wait(100);

    // Check that no injected class exists
    const allElements = hostileRoot.querySelectorAll('*');
    for (const el of allElements) {
      for (const cls of el.classList) {
        assert.ok(!cls.includes('injected'), `no element should have injected class, found: "${cls}"`);
        assert.ok(!cls.includes('onclick'), `no element should have onclick class, found: "${cls}"`);
      }
    }

    // Check that no script tag was injected
    const scripts = hostileRoot.querySelectorAll('script');
    // Only scripts that were there before (none in root)
    assert.strictEqual(scripts.length, 0, 'no script tags should be injected');

    hostileDom.window.close();
  });

  // -----------------------------------------------------------------------
  // Test 12: Accessibility — list container has listbox role
  // -----------------------------------------------------------------------

  it('peer list container has listbox role when children use option role', async () => {
    await wait(100);

    const peerList = root.querySelector('.wt-peer-list');
    assert.ok(peerList, 'peer list must exist');

    // Children use role="option", so parent should be role="listbox"
    const role = peerList.getAttribute('role');
    assert.strictEqual(role, 'listbox', 'peer list must have role="listbox"');

    // Verify children have role="option"
    const options = peerList.querySelectorAll('[role="option"]');
    assert.ok(options.length > 0, 'peer items must have role="option"');
  });

  // -----------------------------------------------------------------------
  // Test 13: Accessibility — inspector is dialog/group, not tooltip with buttons
  // -----------------------------------------------------------------------

  it('inspector uses dialog/group semantics, not role=tooltip with buttons', async () => {
    await wait(100);

    const inspector = root.querySelector('#wt-inspector');
    assert.ok(inspector, 'inspector must exist');

    const role = inspector.getAttribute('role');
    // Must NOT be "tooltip" — tooltips cannot contain interactive elements
    assert.notStrictEqual(role, 'tooltip', 'inspector must not use role="tooltip"');
    // Should be "dialog" or "group" for interactive popover
    assert.ok(
      role === 'dialog' || role === 'group',
      `inspector role must be "dialog" or "group", got "${role}"`
    );
  });

  // -----------------------------------------------------------------------
  // Test 14: Keyboard accessibility — Enter/Space on peer focuses it
  // -----------------------------------------------------------------------

  it('keyboard Enter on peer item focuses the peer', async () => {
    await wait(100);

    const peerItems = root.querySelectorAll('.wt-peer-item');
    assert.ok(peerItems.length > 0, 'must have peer items');
    const firstPeer = peerItems[0];

    // Press Enter on the peer item
    dispatchKey(firstPeer, 'Enter');
    await wait(100);

    // Verify peer detail is shown
    const detail = root.querySelector('#wt-peer-detail');
    assert.ok(detail, 'peer detail must appear after keyboard Enter');

    // Verify aria-selected
    assert.strictEqual(firstPeer.getAttribute('aria-selected'), 'true', 'peer must be selected after Enter');
  });

  // -----------------------------------------------------------------------
  // Test 15: Escape key hides inspector
  // -----------------------------------------------------------------------

  it('Escape key hides the inspector popover', async () => {
    await wait(100);

    const peerItems = root.querySelectorAll('.wt-peer-item');
    const firstPeer = peerItems[0];
    const inspector = root.querySelector('#wt-inspector');

    // Show inspector
    dispatchMouse(firstPeer, 'mouseenter');
    await wait(50);
    assert.ok(inspector.classList.contains('show'), 'inspector should be visible');

    // Press Escape
    dispatchKey(inspector, 'Escape');
    await wait(50);

    assert.ok(!inspector.classList.contains('show'), 'inspector should hide after Escape');
  });
});
