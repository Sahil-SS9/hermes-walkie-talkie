/**
 * Tests for the Walkie-Talkie Dashboard plugin build and API assets.
 *
 * Run with: node --experimental-vm-modules --test tests/*.test.mjs
 */

import { describe, it, before } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync, existsSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIST_DIR = join(__dirname, '..', 'dist');
const MANIFEST_PATH = join(__dirname, '..', 'manifest.json');

// ---------------------------------------------------------------------------
// Build output integrity
// ---------------------------------------------------------------------------

describe('Build output integrity', () => {
  it('dist/index.js exists and is non-empty', () => {
    const path = join(DIST_DIR, 'index.js');
    assert.ok(existsSync(path), 'dist/index.js must exist');
    const content = readFileSync(path, 'utf-8');
    assert.ok(content.length > 1000, 'dist/index.js must be > 1KB');
  });

  it('dist/style.css exists and is non-empty', () => {
    const path = join(DIST_DIR, 'style.css');
    assert.ok(existsSync(path), 'dist/style.css must exist');
    const content = readFileSync(path, 'utf-8');
    assert.ok(content.length > 1000, 'dist/style.css must be > 1KB');
  });

  it('dist/index.js contains expected API symbols', () => {
    const content = readFileSync(join(DIST_DIR, 'index.js'), 'utf-8');
    // The bundled output should contain the API route paths
    assert.ok(content.includes('/health'), 'must contain /health route');
    assert.ok(content.includes('/peers'), 'must contain /peers route');
    assert.ok(content.includes('/groups'), 'must contain /groups route');
    assert.ok(content.includes('/inbox'), 'must contain /inbox route');
    assert.ok(content.includes('/requests'), 'must contain /requests route');
    assert.ok(content.includes('/events'), 'must contain /events socket route');
  });

  it('dist/index.js contains theme definitions', () => {
    const content = readFileSync(join(DIST_DIR, 'index.js'), 'utf-8');
    // All 7 theme IDs should be present
    assert.ok(content.includes('ember'), 'must contain ember theme');
    assert.ok(content.includes('signal'), 'must contain signal theme');
    assert.ok(content.includes('watch'), 'must contain watch theme');
    assert.ok(content.includes('violet'), 'must contain violet theme');
    assert.ok(content.includes('arctic'), 'must contain arctic theme');
    assert.ok(content.includes('forest'), 'must contain forest theme');
    assert.ok(content.includes('paper'), 'must contain paper theme');
  });

  it('dist/index.js contains speech-to-text fallback', () => {
    const content = readFileSync(join(DIST_DIR, 'index.js'), 'utf-8');
    assert.ok(
      content.includes('Speech-to-text unavailable') || content.includes('unavailable'),
      'must contain STT unavailable fallback message'
    );
  });

  it('dist/index.js contains Control Room reference', () => {
    const content = readFileSync(join(DIST_DIR, 'index.js'), 'utf-8');
    assert.ok(content.includes('Control Room'), 'must contain Control Room');
  });

  it('dist/index.js contains transmission icon markup', () => {
    const content = readFileSync(join(DIST_DIR, 'index.js'), 'utf-8');
    assert.ok(content.includes('wt-radio') || content.includes('wt-wave'), 'must contain transmission icon classes');
  });

  it('dist/style.css contains required CSS classes', () => {
    const content = readFileSync(join(DIST_DIR, 'style.css'), 'utf-8');
    const required = [
      '.wt-dashboard',
      '.wt-header',
      '.wt-mark',
      '.wt-rail',
      '.wt-workspace',
      '.wt-tabs',
      '.wt-overlay',
      '.wt-modal',
      '.wt-stt-panel',
      '.wt-inspector',
      '.wt-control-room',
      '.wt-peer-item',
      '.wt-theme-pop',
    ];
    for (const cls of required) {
      assert.ok(content.includes(cls), `CSS must contain ${cls}`);
    }
  });

  it('dist/style.css contains theme variable fallbacks', () => {
    const content = readFileSync(join(DIST_DIR, 'style.css'), 'utf-8');
    assert.ok(content.includes('--canvas'), 'must contain --canvas variable');
    assert.ok(content.includes('--signal'), 'must contain --signal variable');
    assert.ok(content.includes('--ink'), 'must contain --ink variable');
  });

  it('dist/style.css contains transmission animation', () => {
    const content = readFileSync(join(DIST_DIR, 'style.css'), 'utf-8');
    assert.ok(content.includes('wt-transmit') || content.includes('transmit'), 'must contain transmission animation');
  });
});

// ---------------------------------------------------------------------------
// Manifest compliance
// ---------------------------------------------------------------------------

describe('Manifest compliance', () => {
  let manifest;

  before(() => {
    manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf-8'));
  });

  it('manifest.json references dist/index.js as entry', () => {
    assert.strictEqual(manifest.entry, 'dist/index.js');
  });

  it('manifest.json references dist/style.css as css', () => {
    assert.strictEqual(manifest.css, 'dist/style.css');
  });

  it('manifest.json references plugin_api.py as api', () => {
    assert.strictEqual(manifest.api, 'plugin_api.py');
  });

  it('manifest.json has required fields', () => {
    assert.ok(manifest.name, 'must have name');
    assert.ok(manifest.label, 'must have label');
    assert.ok(manifest.version, 'must have version');
    assert.ok(manifest.icon, 'must have icon');
    assert.ok(manifest.tab, 'must have tab');
  });

  it('manifest.json tab has path and position', () => {
    assert.ok(manifest.tab.path, 'tab must have path');
    assert.ok(manifest.tab.position, 'tab must have position');
  });

  it('dist files referenced in manifest actually exist', () => {
    assert.ok(existsSync(join(DIST_DIR, 'index.js')), 'entry file must exist');
    assert.ok(existsSync(join(DIST_DIR, 'style.css')), 'css file must exist');
  });
});

// ---------------------------------------------------------------------------
// API client contract
// ---------------------------------------------------------------------------

describe('API client contract (source-level)', () => {
  it('api.ts source exports createApi function', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'api.ts'), 'utf-8');
    assert.ok(src.includes('export function createApi'), 'must export createApi');
  });

  it('api.ts defines all required endpoint methods', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'api.ts'), 'utf-8');
    const methods = [
      'health',
      'metrics',
      'peers',
      'groups',
      'createGroup',
      'groupMembers',
      'addMember',
      'broadcastOutcomes',
      'inbox',
      'requests',
      'requestDetail',
      'respond',
      'onEvents',
    ];
    for (const m of methods) {
      assert.ok(src.includes(`${m}:`), `api.ts must define ${m} method`);
    }
  });

  it('api.ts uses only public API endpoints (no SQLite/private reads)', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'api.ts'), 'utf-8');
    // Must not contain any direct SQLite or filesystem references
    assert.ok(!src.includes('sqlite'), 'must not reference sqlite');
    assert.ok(!src.includes('readFile'), 'must not read filesystem');
    // registry_entries is a field in the HealthView response from the public API — that's fine
    // But there should be no direct registry access patterns
    assert.ok(!src.includes('import registry'), 'must not import registry');
    assert.ok(!src.includes('from registry'), 'must not import from registry');
  });
});

// ---------------------------------------------------------------------------
// Theme system
// ---------------------------------------------------------------------------

describe('Theme system (source-level)', () => {
  it('theme.ts defines exactly 7 themes', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'theme.ts'), 'utf-8');
    const themeIdMatches = src.match(/id:\s*'(\w+)'/g);
    assert.ok(themeIdMatches, 'must have theme IDs');
    assert.strictEqual(themeIdMatches.length, 7, 'must have exactly 7 themes');
  });

  it('theme.ts has Ember Relay as first/default theme', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'theme.ts'), 'utf-8');
    const firstId = src.match(/id:\s*'(\w+)'/)?.[1];
    assert.strictEqual(firstId, 'ember', 'first theme must be ember');
  });

  it('theme.ts uses localStorage for persistence', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'theme.ts'), 'utf-8');
    assert.ok(src.includes('localStorage'), 'must use localStorage');
    assert.ok(src.includes('walkie-talkie-theme'), 'must use walkie-talkie-theme key');
  });

  it('theme.ts exports applyTheme, getStoredTheme, setStoredTheme, getThemeById', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'theme.ts'), 'utf-8');
    assert.ok(src.includes('export function applyTheme'), 'must export applyTheme');
    assert.ok(src.includes('export function getStoredTheme'), 'must export getStoredTheme');
    assert.ok(src.includes('export function setStoredTheme'), 'must export setStoredTheme');
    assert.ok(src.includes('export function getThemeById'), 'must export getThemeById');
  });
});

// ---------------------------------------------------------------------------
// Speech-to-text
// ---------------------------------------------------------------------------

describe('Speech-to-text (source-level)', () => {
  it('speech-to-text component checks for SpeechRecognition API', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'components', 'speech-to-text.ts'), 'utf-8');
    assert.ok(src.includes('SpeechRecognition'), 'must check SpeechRecognition');
    assert.ok(src.includes('webkitSpeechRecognition'), 'must check webkitSpeechRecognition');
  });

  it('speech-to-text component has explicit unavailable fallback', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'components', 'speech-to-text.ts'), 'utf-8');
    assert.ok(
      src.includes('Speech-to-text unavailable') || src.includes('unavailable'),
      'must have unavailable fallback message'
    );
  });
});

// ---------------------------------------------------------------------------
// Control Room
// ---------------------------------------------------------------------------

describe('Control Room (source-level)', () => {
  it('control-room component is attention/deep-link only', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'components', 'control-room.ts'), 'utf-8');
    assert.ok(src.includes('Control Room'), 'must reference Control Room');
    assert.ok(src.includes('deep-link'), 'must be deep-link only');
    // Must not contain full Control Room implementation
    assert.ok(!src.includes('SQLite'), 'must not access SQLite');
  });
});

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

describe('Modals (source-level)', () => {
  it('modals component renders overlay with close behavior', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'components', 'modals.ts'), 'utf-8');
    assert.ok(src.includes('wt-overlay'), 'must have overlay class');
    assert.ok(src.includes('wt-modal'), 'must have modal class');
    assert.ok(src.includes('Escape'), 'must close on Escape key');
  });
});

// ---------------------------------------------------------------------------
// Peer inspector
// ---------------------------------------------------------------------------

describe('Peer inspector (source-level)', () => {
  it('peer-rail component renders inspector popover', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'components', 'peer-rail.ts'), 'utf-8');
    assert.ok(src.includes('wt-inspector'), 'must have inspector element');
  });

  it('app.ts wires peer hover to inspector', () => {
    const src = readFileSync(join(__dirname, '..', 'src', 'app.ts'), 'utf-8');
    assert.ok(src.includes('mouseenter'), 'must handle mouseenter for inspector');
    assert.ok(src.includes('wt-inspector'), 'must reference wt-inspector');
  });
});
