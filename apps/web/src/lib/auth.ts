// Authentication helpers — in-memory access token + server-side refresh cookie.
//
// Per AGENTS.md §Authz and audit §4.1:
//   "access в памяти (15min), refresh в httpOnly cookie (30 days)"
//
// The access token lives only in module-level JS state (NOT localStorage)
// so it is reset on full page reload. After reload, the Layout component
// calls /api/v1/auth/refresh — which reads the httpOnly refresh cookie
// server-side and returns a fresh access token. The cookie itself is
// never visible to JavaScript.
//
// Trade-off: a full page reload briefly interrupts the session (one
// network round-trip to /refresh). In exchange, XSS cannot directly
// exfiltrate the access or refresh token.

import type { AuthUser } from '@/lib/auth';

const REFRESH_ENDPOINT = '/api/v1/auth/refresh';

let _accessToken: string | null = null;
let _user: AuthUser | null = null;
let _refreshInflight: Promise<string | null> | null = null;
const _listeners = new Set<(state: { accessToken: string | null; user: AuthUser | null }) => void>();


export function getAccessToken(): string | null {
  return _accessToken;
}

export function getCurrentUser(): AuthUser | null {
  return _user;
}

export function setAuth(accessToken: string, user: AuthUser): void {
  _accessToken = accessToken;
  _user = user;
  _emit();
}

export function clearAuth(): void {
  _accessToken = null;
  _user = null;
  _emit();
}

export function subscribeAuth(
  listener: (state: { accessToken: string | null; user: AuthUser | null }) => void,
): () => void {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}

function _emit(): void {
  for (const listener of _listeners) {
    listener({ accessToken: _accessToken, user: _user });
  }
}


/**
 * Restore session state after page reload.
 *
 * Calls /auth/refresh — the server reads the httpOnly refresh cookie
 * and returns a fresh access token. On success, populates the in-memory
 * state. On failure, leaves state empty (user must log in again).
 *
 * Concurrent callers share a single in-flight request via
 * _refreshInflight, so a single page reload doesn't trigger N refresh
 * requests when N components mount simultaneously.
 */
export async function restoreSession(): Promise<boolean> {
  if (_accessToken) {
    return true;
  }
  if (_refreshInflight) {
    const token = await _refreshInflight;
    return token !== null;
  }

  _refreshInflight = (async () => {
    try {
      const r = await fetch(REFRESH_ENDPOINT, {
        method: 'POST',
        credentials: 'include',  // send httpOnly refresh cookie
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),  // refresh token comes from cookie, body is empty
      });
      if (!r.ok) {
        return null;
      }
      const data = await r.json();
      if (data.access_token && data.user) {
        _accessToken = data.access_token;
        _user = data.user;
        _emit();
        return data.access_token;
      }
      return null;
    } catch {
      return null;
    } finally {
      _refreshInflight = null;
    }
  })();

  const token = await _refreshInflight;
  return token !== null;
}


/**
 * Logout — tells the server to blacklist the refresh token and clear
 * the cookie, then clears local in-memory state.
 */
export async function logout(): Promise<void> {
  try {
    await fetch('/api/v1/auth/logout', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
  } catch {
    // Ignore network errors — we still want to clear local state.
  }
  clearAuth();
}


// Re-export the type so the rest of the codebase can `import { AuthUser }
// from '@/lib/auth'` without changing.
export type { AuthUser };

// Legacy interface kept for compatibility with the older auth.ts API
// surface (some pages still call getStoredAuth()).
export interface AuthState {
  access_token: string;
  user: AuthUser;
}

export function getStoredAuth(): AuthState | null {
  if (_accessToken && _user) {
    return { access_token: _accessToken, user: _user };
  }
  return null;
}

export function setStoredAuth(_state: AuthState): void {
  // No-op: storage is now in-memory only + httpOnly cookie.
  // This function is kept as a thin wrapper so existing call sites
  // that pair it with `getStoredAuth()` keep working. New code should
  // call setAuth() directly.
}

export function clearStoredAuth(): void {
  clearAuth();
}

// Compatibility shim: older code reads `kamilya_token` from the cookie
// set by the previous localStorage-based flow. That cookie is no longer
// set. Read access from in-memory state instead.
const LEGACY_TOKEN_COOKIE = 'kamilya_token';
export function getLegacyTokenCookie(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp('(?:^|; )' + LEGACY_TOKEN_COOKIE + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}