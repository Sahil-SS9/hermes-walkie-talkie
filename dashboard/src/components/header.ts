/**
 * Header component — transmission icon, brand, theme picker, profile badge.
 */

import type { AppState } from '../types';
import { THEMES } from '../theme';

export function renderHeader(state: AppState, onThemeChange: (id: string) => void): HTMLElement {
  const header = document.createElement('header');
  header.className = 'wt-header';

  // Transmission icon
  const mark = document.createElement('div');
  mark.className = 'wt-mark';
  mark.setAttribute('aria-label', 'Walkie-Talkie transmission');
  mark.innerHTML = `
    <div class="wt-radio"></div>
    <div class="wt-wave"></div>
    <div class="wt-wave wt-wave-two"></div>
  `;
  header.appendChild(mark);

  // Brand
  const brand = document.createElement('div');
  brand.className = 'wt-brand-group';
  brand.innerHTML = '<div class="wt-brand">Walkie-Talkie</div><div class="wt-sub">Detailed peer collaboration</div>';
  header.appendChild(brand);

  // Spacer
  const spacer = document.createElement('div');
  spacer.className = 'wt-grow';
  header.appendChild(spacer);

  // Theme picker
  const themeBtn = document.createElement('button');
  themeBtn.className = 'wt-header-btn';
  const currentTheme = THEMES.find((t) => t.id === state.activeTheme) || THEMES[0];
  themeBtn.textContent = currentTheme.label + ' ▾';
  themeBtn.setAttribute('aria-label', 'Select workspace theme');

  const themePop = document.createElement('div');
  themePop.className = 'wt-theme-pop';
  themePop.id = 'wt-theme-pop';
  themePop.innerHTML = '<div class="wt-theme-title">Workspace themes</div>';
  const themeList = document.createElement('div');
  themeList.className = 'wt-themes';
  for (const t of THEMES) {
    const btn = document.createElement('button');
    btn.className = 'wt-theme-option';
    btn.setAttribute('data-theme', t.id);
    btn.innerHTML = `<i class="wt-swatch" style="--sw:${t.vars['--signal']}"></i>${t.label}`;
    btn.onclick = (e) => {
      e.stopPropagation();
      onThemeChange(t.id);
      themeBtn.textContent = t.label + ' ▾';
      themePop.classList.remove('show');
    };
    themeList.appendChild(btn);
  }
  themePop.appendChild(themeList);

  themeBtn.onclick = (e) => {
    e.stopPropagation();
    themePop.classList.toggle('show');
  };
  document.addEventListener('click', () => themePop.classList.remove('show'));

  header.appendChild(themeBtn);
  header.appendChild(themePop);

  // Profile badge
  const profileBtn = document.createElement('button');
  profileBtn.className = 'wt-header-btn';
  profileBtn.textContent = 'kensei / default';
  profileBtn.setAttribute('aria-label', 'Current profile');
  header.appendChild(profileBtn);

  return header;
}
