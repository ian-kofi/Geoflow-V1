import { useCallback, useEffect, useState } from 'react';
import { THEME_KEY } from './config.js';

function initialTheme() {
  const applied = document.documentElement.dataset.theme; // set by the inline script in index.html
  if (applied === 'light' || applied === 'dark') return applied;
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

/** 'light' | 'dark', remembered in localStorage and applied as <html data-theme>. */
export function useTheme() {
  const [theme, setTheme] = useState(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable — the theme just won't persist */
    }
  }, [theme]);

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);
  return { theme, toggleTheme };
}
