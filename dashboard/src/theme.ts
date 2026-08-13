/**
 * Theme system — 7 persistent local themes stored in localStorage.
 * Ember Relay is the default.
 */

export interface ThemeVars {
  '--canvas': string;
  '--surface': string;
  '--surface-raised': string;
  '--line': string;
  '--ink': string;
  '--quiet': string;
  '--signal': string;
  '--signal-soft': string;
  '--safe': string;
  '--danger': string;
  '--hold': string;
}

export interface ThemeDef {
  id: string;
  label: string;
  vars: ThemeVars;
}

export const THEMES: ThemeDef[] = [
  {
    id: 'ember',
    label: 'Ember Relay',
    vars: {
      '--canvas': '#110e0b', '--surface': '#1a140f', '--surface-raised': '#211914',
      '--line': '#4b3827', '--ink': '#fff2dc', '--quiet': '#c2aa89',
      '--signal': '#ef8138', '--signal-soft': '#ffc36c', '--safe': '#9edb79',
      '--danger': '#ff7380', '--hold': '#ffc45b',
    },
  },
  {
    id: 'signal',
    label: 'Signal Dark',
    vars: {
      '--canvas': '#080e12', '--surface': '#101a20', '--surface-raised': '#172a31',
      '--line': '#315362', '--ink': '#e8fbff', '--quiet': '#9fc5cf',
      '--signal': '#40c7e9', '--signal-soft': '#9deaff', '--safe': '#8bdab0',
      '--danger': '#ff7380', '--hold': '#ffc45b',
    },
  },
  {
    id: 'watch',
    label: 'Night Watch',
    vars: {
      '--canvas': '#0b100c', '--surface': '#141a12', '--surface-raised': '#1c2519',
      '--line': '#405035', '--ink': '#f1f9e8', '--quiet': '#b6c3aa',
      '--signal': '#b4d879', '--signal-soft': '#e0f5a4', '--safe': '#a8d77c',
      '--danger': '#ff7380', '--hold': '#ffc45b',
    },
  },
  {
    id: 'violet',
    label: 'Violet Frequency',
    vars: {
      '--canvas': '#110d18', '--surface': '#1b1426', '--surface-raised': '#261c34',
      '--line': '#51426a', '--ink': '#f5efff', '--quiet': '#c5b6d7',
      '--signal': '#a88cf2', '--signal-soft': '#d7c6ff', '--safe': '#a2ddb9',
      '--danger': '#ff7380', '--hold': '#ffc45b',
    },
  },
  {
    id: 'arctic',
    label: 'Arctic Channel',
    vars: {
      '--canvas': '#081117', '--surface': '#11212c', '--surface-raised': '#18303d',
      '--line': '#3b627a', '--ink': '#eaf7ff', '--quiet': '#aecbd9',
      '--signal': '#74b8e6', '--signal-soft': '#c4e9ff', '--safe': '#86dcbe',
      '--danger': '#ff7380', '--hold': '#ffc45b',
    },
  },
  {
    id: 'forest',
    label: 'Forest Ops',
    vars: {
      '--canvas': '#08110e', '--surface': '#112019', '--surface-raised': '#183126',
      '--line': '#38614d', '--ink': '#e9fff5', '--quiet': '#a9c9b8',
      '--signal': '#6fc9a2', '--signal-soft': '#b8f2d1', '--safe': '#8fdca6',
      '--danger': '#ff7380', '--hold': '#ffc45b',
    },
  },
  {
    id: 'paper',
    label: 'Paper Terminal',
    vars: {
      '--canvas': '#f3f0e8', '--surface': '#fbf9f3', '--surface-raised': '#ffffff',
      '--line': '#cfc6b5', '--ink': '#17233a', '--quiet': '#687084',
      '--signal': '#2668ca', '--signal-soft': '#174a9c', '--safe': '#2e8b67',
      '--danger': '#c0392b', '--hold': '#d4a017',
    },
  },
];

const STORAGE_KEY = 'walkie-talkie-theme';

export function getStoredTheme(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || 'ember';
  } catch {
    return 'ember';
  }
}

export function setStoredTheme(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch { /* noop */ }
}

export function applyTheme(theme: ThemeDef): void {
  const root = document.documentElement;
  for (const [key, value] of Object.entries(theme.vars)) {
    root.style.setProperty(key, value);
  }
}

export function getThemeById(id: string): ThemeDef {
  return THEMES.find((t) => t.id === id) || THEMES[0];
}
