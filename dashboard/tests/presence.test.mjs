/**
 * Presence remediation behaviour tests (G1–G6) — run against the DIST bundle.
 *
 * These mount the app in jsdom with a presence-flavoured mock SDK and assert
 * the mockup contract directly on the DOM:
 *   G1  — dot classes (.dot.g/.a/.q/.r) map the real enum + derived offline
 *   G2  — rail eyebrow shows "Live sessions · N · M active"
 *   G3  — local row carries .me + a `you` pill
 *   G4  — per-peer activity line (.wt-act) under each name
 *   G5  — liveness line (.wt-live) renders "● Live · updated …"; reconnecting
 *         state flips it to "○ reconnecting" with .off
 *   G6  — offline rows render red .dot.r, dimmed .item.off and "offline" label
 *
 * Run with: node --experimental-vm-modules --test tests/presence.test.mjs
 * (after `node build.mjs` — the behaviour tests assert the DIST bundle).
 */

import { describe, it, before, after } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIST_DIR = join(__dirname, '..', 'dist');
const BUNDLE_PATH = join(DIST_DIR, 'index.js');

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Mock SDK with presence-aware data:
 *  - /peers returns the raw list (statuses working/idle/offline-ish)
 *  - /peers/summary returns aggregate + per-peer offline flags + you_peer_id
 */
function createPresenceSDK(overrides = {}) {
  const nowIso = new Date().toISOString();
  const peers = [
    { peer_id: 'peer-1', agent_id: 'agent-alpha-001', name: 'Alpha', profile: 'default', surface: 'cli', status: 'working', current_activity: 'researching…', cwd: '/home/alpha', git_branch: 'main' },
    { peer_id: 'peer-2', agent_id: 'agent-beta-002', name: 'Beta', profile: 'coder', surface: 'desktop', status: 'held', current_activity: 'code review', cwd: '/home/beta', git_branch: 'feat/x' },
    { peer_id: 'peer-3', agent_id: 'agent-gamma-003', name: 'Gamma', profile: 'default', surface: 'cli', status: 'idle', current_activity: '', cwd: '/home/gamma', git_branch: 'develop' },
    { peer_id: 'peer-4', agent_id: 'agent-delta-004', name: 'Delta', profile: 'default', surface: 'cli', status: 'working', current_activity: 'scanning arxiv', cwd: '/home/delta', git_branch: 'main' },
  ];
  const summary = {
    total: 4,
    live_count: 4,
    active_count: 3,
    idle_count: 0,
    offline_count: 1,
    you_peer_id: 'peer-1',
    last_updated: nowIso,
    peers: [
      { ...peers[0], offline: false, status_label: 'working' },
      { ...peers[1], offline: false, status_label: 'held' },
      { ...peers[2], offline: false, status_label: 'idle' },
      { ...peers[3], offline: true, status_label: 'offline' },
    ],
  };

  const sdk = {
    sdkVersion: '1.1.0',
    React: { createElement: (tag, props, ...children) => (typeof tag === 'function' ? tag(props) : { tag, props, children }) },
    hooks: {
      useState: (init) => [init, () => {}],
      useEffect: (fn) => { fn(); },
      useCallback: (fn) => fn,
      useMemo: (fn) => fn(),
      useRef: (init) => ({ current: init }),
      useContext: () => ({}),
      createContext: () => ({ Provider: () => null, Consumer: () => null }),
    },
    api: { getActiveProfile: async () => ({ current: 'default', active: 'test-profile' }) },
    fetchJSON: async (url) => {
      if (overrides.fetchJSON) return overrides.fetchJSON(url);
      if (url.includes('/peers/summary')) return summary;
      if (url.includes('/peers')) return { peers };
      if (url.includes('/requests')) return { requests: [] };
      if (url.includes('/inbox')) return { messages: [] };
      if (url.includes('/groups')) return { groups: [] };
      if (url.includes('/health')) {
        return { ok: true, backend: 'sqlite', runtime_dir: '/tmp', registry_entries: 4, live_peers: 4, pending_messages: 0, held_messages: 0, problems: [] };
      }
      return {};
    },
    authedFetch: async () => new Response(),
    buildWsUrl: async () => (overrides.wsUrl || 'ws://localhost/ws'),
    buildWsAuthParam: async () => ['token', 'test'],
    components: {},
    utils: { cn: (...a) => a.filter(Boolean).join(' '), timeAgo: () => 'just now', isoTimeAgo: () => 'just now' },
    useI18n: () => ({ t: (k) => k }),
  };
  return { sdk, peers, summary };
}

function mount(dom, sdk) {
  const root = dom.window.document.getElementById('root');
  dom.window.__wt_initApp(sdk, root);
  return root;
}

describe('Presence remediation (G1–G6) — dist bundle behaviour', () => {
  let dom;
  let mock;
  let root;

  before(async () => {
    assert.ok(existsSync(BUNDLE_PATH), 'dist/index.js must exist — run `node build.mjs` first');
    dom = new JSDOM('<!DOCTYPE html><html><head></head><body><div id="root"></div></body></html>', {
      url: 'http://localhost/',
      runScripts: 'dangerously',
      resources: 'usable',
    });
    dom.window.Response = class Response {
      constructor(body, init) { this._body = body; this.status = init?.status || 200; }
      json() { return Promise.resolve(JSON.parse(this._body)); }
      text() { return Promise.resolve(this._body); }
    };
    dom.window.navigator.clipboard = { writeText: async () => {} };
    // Provide a working WebSocket: jsdom has none. onopen fires → connected.
    const wsOpenHandlers = new Set();
    dom.window.WebSocket = class {
      constructor() {
        this.readyState = 0;
        wsOpenHandlers.add(this);
      }
      close() { wsOpenHandlers.delete(this); }
      // let the host trigger onopen/onerror/onclose
    };
    mock = createPresenceSDK();
    dom.window.__HERMES_PLUGIN_SDK__ = mock.sdk;
    dom.window.__HERMES_PLUGINS__ = { register() {}, registerSlot() {} };
    const bundle = readFileSync(BUNDLE_PATH, 'utf-8');
    try {
      dom.window.eval(bundle);
    } catch (err) {
      if (!err.message?.includes('WebSocket')) throw err;
    }
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded', { bubbles: true, cancelable: true }));
    await wait(120);
    root = mount(dom, mock.sdk);
    await wait(150); // initial refresh settles
    // Fire onopen on sockets created by initApp so the WS state becomes 'connected'
    for (const ws of wsOpenHandlers) {
      if (typeof ws.onopen === 'function') ws.onopen();
    }
    await wait(50);
  });

  after(() => { if (dom) dom.window.close(); });

  it('G2: rail eyebrow shows "Live sessions · N · M working"', async () => {
    const eyebrow = root.querySelector('#wt-eyebrow');
    assert.ok(eyebrow, 'eyebrow must exist');
    assert.ok(eyebrow.textContent.includes('Live sessions · 4'), `got: ${eyebrow.textContent}`);
    assert.ok(eyebrow.textContent.includes('3 working'), `got: ${eyebrow.textContent}`);
  });

  it('G1: dots map the real enum — working→.g, held→.a, idle→.q, offline→.r', async () => {
    const items = root.querySelectorAll('.wt-peer-item');
    assert.ok(items.length >= 4, `expected 4 peers, got ${items.length}`);
    const byPeer = new Map();
    for (const item of items) {
      // The name <b> contains the peer name, possibly followed by a you pill
      const b = item.querySelector('.wt-peer-info b');
      const name = (b?.textContent || '').replace('you', '').trim();
      const dot = item.querySelector('.wt-presence.dot');
      if (dot) byPeer.set(name, dot.className);
    }
    assert.match(byPeer.get('Alpha') || '', /dot g/, `working → .dot.g, got: ${byPeer.get('Alpha')}`);
    assert.match(byPeer.get('Beta') || '', /dot a/, `held → .dot.a, got: ${byPeer.get('Beta')}`);
    assert.match(byPeer.get('Gamma') || '', /dot q/, `idle → .dot.q, got: ${byPeer.get('Gamma')}`);
    assert.match(byPeer.get('Delta') || '', /dot r/, `offline → .dot.r, got: ${byPeer.get('Delta')}`);
  });

  it('G3: local session row has .me class + `you` pill', async () => {
    const meItem = Array.from(root.querySelectorAll('.wt-peer-item')).find((li) =>
      (li.querySelector('.wt-peer-info b')?.textContent || '').includes('Alpha'));
    assert.ok(meItem, 'local (Alpha) row must exist');
    assert.ok(meItem.classList.contains('me'), 'local row must have .me');
    const youPill = meItem.querySelector('.wt-you');
    assert.ok(youPill, 'local row must carry a `you` pill');
    assert.ok(youPill.textContent.toLowerCase().includes('you'), `pill text: ${youPill.textContent}`);
    // Non-local rows must NOT have the pill
    const betaItem = Array.from(root.querySelectorAll('.wt-peer-item')).find((li) =>
      (li.querySelector('.wt-peer-info b')?.textContent || '').includes('Beta'));
    assert.ok(!betaItem.querySelector('.wt-you'), 'remote row must not carry you pill');
  });

  it('G4: per-peer activity line renders under the name', async () => {
    const alphaItem = Array.from(root.querySelectorAll('.wt-peer-item')).find((li) =>
      (li.querySelector('.wt-peer-info b')?.textContent || '').includes('Alpha'));
    const act = alphaItem.querySelector('.wt-act');
    assert.ok(act, 'working peer must have activity line');
    assert.ok(act.textContent.includes('researching'), `activity text: ${act.textContent}`);
    assert.ok(act.classList.contains('g'), 'working activity line must be .act.g');
    // idle peer without activity shows no line
    const gammaItem = Array.from(root.querySelectorAll('.wt-peer-item')).find((li) =>
      (li.querySelector('.wt-peer-info b')?.textContent || '').includes('Gamma'));
    assert.ok(!gammaItem.querySelector('.wt-act'), 'idle peer without activity must have no line');
  });

  it('G6: offline row is dimmed (.item.off), red dot, and labelled offline', async () => {
    const deltaItem = Array.from(root.querySelectorAll('.wt-peer-item')).find((li) =>
      (li.querySelector('.wt-peer-info b')?.textContent || '').includes('Delta'));
    assert.ok(deltaItem, 'offline peer row must exist');
    assert.ok(deltaItem.classList.contains('off'), 'offline row must have .item.off');
    const dot = deltaItem.querySelector('.wt-presence.dot');
    assert.ok(dot, 'offline row must have a dot');
    assert.match(dot.className, /dot r/, 'offline dot must be .dot.r');
    const small = deltaItem.querySelector('.wt-peer-info small');
    assert.ok(small.textContent.includes('offline'), `offline label, got: ${small.textContent}`);
  });

  it('G5: liveness line renders "● Live · updated …" from summary.last_updated', async () => {
    const live = root.querySelector('#wt-live');
    assert.ok(live, 'liveness line must exist');
    assert.match(live.textContent, /● Live · updated/, `got: ${live.textContent}`);
    assert.ok(!live.classList.contains('off'), 'connected state must not be .off');
  });

  it('G5: WS drop flips to "○ reconnecting" + .off, and a successful poll recovers (R1)', async () => {
    // Contract: the liveness label maps wsState deterministically (unit).
    const { liveLabel } = await import('../src/components/peer-rail.ts');
    const rec = liveLabel('reconnecting', 1, '2026-01-01T00:00:00Z');
    assert.match(rec, /reconnecting/, `reconnecting label, got: ${rec}`);
    const conn = liveLabel('connected', 1, '2026-01-01T00:00:00Z');
    assert.match(conn, /Live/, `connected label, got: ${conn}`);

    // Integration: a mount whose WS fails (buildWsUrl throws) but whose
    // polls succeed must RECOVER to connected — never stuck on reconnecting.
    const dom2 = new JSDOM('<!DOCTYPE html><html><head></head><body><div id="root"></div></body></html>', {
      url: 'http://localhost/',
      runScripts: 'dangerously',
      resources: 'usable',
    });
    dom2.window.Response = class Response {
      constructor(body, init) { this._body = body; this.status = init?.status || 200; }
      json() { return Promise.resolve(JSON.parse(this._body)); }
      text() { return Promise.resolve(this._body); }
    };
    dom2.window.navigator.clipboard = { writeText: async () => {} };
    dom2.window.__HERMES_PLUGIN_SDK__ = createPresenceSDK({ wsUrl: '' }).sdk;
    dom2.window.__HERMES_PLUGINS__ = { register() {}, registerSlot() {} };
    // buildWsUrl resolves to a URL that immediately errors -> onerror -> reconnecting
    dom2.window.__HERMES_PLUGIN_SDK__.buildWsUrl = async () => {
      throw new Error('no ws');
    };
    const bundle = readFileSync(BUNDLE_PATH, 'utf-8');
    dom2.window.eval(bundle);
    dom2.window.document.dispatchEvent(new dom2.window.Event('DOMContentLoaded', { bubbles: true, cancelable: true }));
    await wait(120);
    const root2 = dom2.window.document.getElementById('root');
    dom2.window.__wt_initApp(dom2.window.__HERMES_PLUGIN_SDK__, root2);
    await wait(200);
    const live = root2.querySelector('#wt-live');
    assert.ok(live, 'liveness line must exist in degraded mount');
    // The poll succeeds even though WS failed, so the line must NOT be stuck
    // on reconnecting — the UI recovered to a live signal (R1).
    assert.ok(!live.classList.contains('off'), 'successful poll must recover from reconnecting (R1)');
    assert.match(live.textContent, /Live/, `got: ${live.textContent}`);
    dom2.window.close();
  });
});
