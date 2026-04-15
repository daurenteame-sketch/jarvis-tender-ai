/**
 * Token storage — all token reads/writes go through here so we have one place to change.
 * Uses localStorage. SSR-safe (checks for window).
 */

const TOKEN_KEY = 'jarvis_token';

export const getToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
};

export const setToken = (token: string): void => {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
};

export const clearToken = (): void => {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
};
