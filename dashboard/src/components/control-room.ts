/**
 * Control Room — attention banner and deep-link only.
 * Shows count of held messages + pending requests.
 *
 * The "Open Control Room" action is rendered as a disabled button with an
 * explanatory tooltip because the host SDK does not yet expose a
 * programmatic navigation deep-link.  When the SDK adds a router.navigate
 * or similar contract, this can be wired up.
 */

export function renderControlRoom(): HTMLElement {
  const div = document.createElement('div');
  div.className = 'wt-control-room';
  div.id = 'wt-control-room';
  div.style.display = 'none'; // Hidden until items exist

  div.innerHTML = `
    <div class="wt-cr-dot">●</div>
    <div class="wt-cr-text">
      <b>Control Room has <span class="wt-cr-count">0</span> items for you</b>
      <span>Held messages and structured requests that need attention.</span>
    </div>
    <button class="wt-btn" disabled title="Control Room deep-link not yet available in this host SDK version" aria-label="Control Room unavailable">
      Control Room unavailable
    </button>
  `;

  return div;
}
