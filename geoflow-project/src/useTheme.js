import { useCallback, useEffect, useState } from 'react';
import { THEME_KEY } from './config.js';

/** The theme to start with: the one saved last time, otherwise whatever the computer is set to. */
function initialTheme() {
  const applied = document.documentElement.dataset.theme; // set early by a small script in index.html
  if (applied === 'light' || applied === 'dark') return applied;
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

/**
 * Light or dark mode. The choice is saved in the browser and set as <html data-theme="...">,
 * which the colour variables in index.css switch on.
 */
export function useTheme() {
  const [theme, setTheme] = useState(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage isn't available (private browsing, for example), so the theme just won't be remembered */
    }
  }, [theme]);

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);
  return { theme, toggleTheme };
}
