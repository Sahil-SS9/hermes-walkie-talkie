/**
 * Control Room — attention banner and deep-link only.
 * Shows count of held messages + pending requests.
 * Clicking opens the Control Room (deep-link placeholder).
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
    <button class="wt-btn wt-btn-primary" title="Open the compact command surface" aria-label="Open Control Room">
      Open Control Room ↗
    </button>
  `;

  const btn = div.querySelector('button');
  if (btn) {
    btn.onclick = () => {
      // Deep-link placeholder — in production this opens the Control Room surface
      alert('Control Room: deep-link to the compact command surface. (Placeholder — full integration pending.)');
    };
  }

  return div;
}
