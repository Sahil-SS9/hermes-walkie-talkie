/**
 * Modal overlay for receipt and request detail views.
 */

import type { Api } from '../api';

export function renderModals(
  api: Api,
  onDocumentKeydown?: (handler: (event: KeyboardEvent) => void) => void,
): HTMLElement {
  const overlay = document.createElement('div');
  overlay.className = 'wt-overlay';
  overlay.id = 'wt-overlay';

  const modal = document.createElement('div');
  modal.className = 'wt-modal';

  const header = document.createElement('div');
  header.className = 'wt-modal-header';
  header.innerHTML = `
    <h3 id="wt-modal-title">Detail</h3>
    <button class="wt-modal-close" id="wt-modal-close" aria-label="Close modal">✕</button>
  `;
  modal.appendChild(header);

  const body = document.createElement('div');
  body.className = 'wt-modal-body';
  body.id = 'wt-modal-body';
  modal.appendChild(body);

  overlay.appendChild(modal);

  // Close handlers
  const closeBtn = header.querySelector('#wt-modal-close') as HTMLElement;
  if (closeBtn) {
    closeBtn.onclick = () => overlay.classList.remove('show');
  }
  overlay.onclick = (e) => {
    if (e.target === overlay) overlay.classList.remove('show');
  };
  const documentKeydownHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') overlay.classList.remove('show');
  };
  document.addEventListener('keydown', documentKeydownHandler);
  onDocumentKeydown?.(documentKeydownHandler);

  return overlay;
}
