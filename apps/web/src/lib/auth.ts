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
import {
  refreshSession,
  runExclusiveAuthAction,
} from '@/lib/authRefreshCoordinator';

// Trade-off: a full page reload briefly interrupts the session (one
// network round-trip to /refresh). In exchange, XSS cannot directly
// exfiltrate the access or refresh token.

/**
 * Tenant info attached to the user payload — only present for tenant
 * users. Platform superadmins have `tenant: null` and are routed through
 * `/superadmin/*` flows.
 */
export interface AuthUserTenant {
  id: string;
  name: string;
  slug?: string;
  is_demo?: boolean;
}

/**
 * Authenticated user payload kept in memory after login / refresh.
 *
 * Built from /auth/login, /auth/refresh, /invitations/{token}/accept
 * (see `apps/web/src/app/accept-invite/page.tsx` for the canonical
 * assembly) and from the impersonation flow
 * (apps/api/app/modules/users/superadmin_impersonate.py). Keep this in
 * sync if the backend user schema changes.
 */
export interface AuthUser {
  user_id: string;
  tenant_id: string | null;
  tenant: AuthUserTenant | null;
  telegram_id: string;
  role: string;
  roles?: string[];
  full_name: string;
  email: string | null;
  /** Set when this session was minted via superadmin impersonation. */
  impersonated_by?: string;
  impersonated_role?: string;
}

// Absolute URL because the browser fetch in restoreSession runs outside
// axios (which has its own baseURL). Vercel rewrites used to proxy
// /api/v1/* here too, but Vercel's edge strips Set-Cookie on proxied
// responses — that broke the httpOnly refresh-cookie round-trip, which
// meant every page reload kicked the user back to /login.
//
// Going cross-origin instead: CORS is already wired in apps/api
// (ALLOWED_ORIGINS includes https://app.kml.kz), and the browser
// will store the httpOnly refresh cookie normally. The access token
// remains in-memory only (XSS-stealing-resistant).
// NEXT_PUBLIC_API_URL ends in `/api` on Vercel (axios-style baseURL:
//   `${baseURL}/v1/auth/refresh` ⇒ …onrender.com/api/v1/auth/refresh).
// We follow the same convention so the paths line up everywhere. No
// rewrite involved — this hits the backend directly cross-origin.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';
const LOGOUT_ENDPOINT = `${API_BASE}/v1/auth/logout`;
const SWITCH_ROLE_ENDPOINT = `${API_BASE}/v1/auth/switch-role`;

let _accessToken: string | null = null;
let _user: AuthUser | null = null;
let _authEpoch = 0;
let _refreshAndStoreInflight: Promise<boolean> | null = null;
const _listeners = new Set<(state: { accessToken: string | null; user: AuthUser | null }) => void>();


export function getAccessToken(): string | null {
  return _accessToken;
}

export function getCurrentUser(): AuthUser | null {
  return _user;
}

export function setAuth(accessToken: string, user: AuthUser): void {
  _authEpoch += 1;
  _accessToken = accessToken;
  _user = user;
  _emit();
}

export function clearAuth(): void {
  _authEpoch += 1;
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
 * Concurrent callers share one refresh-and-store operation, so all callers
 * observe the same applied result and only one caller advances auth state.
 */
export async function restoreSession(): Promise<boolean> {
  if (_accessToken) {
    return true;
  }

  return refreshAndStoreSession();
}

/**
 * Refresh and apply the result once for this tab. Both startup restoration
 * and API 401 recovery use this boundary so one caller cannot invalidate a
 * sibling caller's epoch after the shared refresh promise resolves.
 */
export function refreshAndStoreSession(): Promise<boolean> {
  return refreshAndStoreSessionInternal(false);
}

/**
 * Force refresh after an API 401. Unlike startup restoration, this must not
 * accept the currently held access token because the failed request used it.
 */
export function forceRefreshAndStoreSession(): Promise<boolean> {
  return refreshAndStoreSessionInternal(true);
}

function refreshAndStoreSessionInternal(force: boolean): Promise<boolean> {
  if (!force && _accessToken) return Promise.resolve(true);
  if (_refreshAndStoreInflight) return _refreshAndStoreInflight;

  const startedAtEpoch = _authEpoch;
  _refreshAndStoreInflight = (async () => {
    const data = await refreshSession();
    if (startedAtEpoch !== _authEpoch || !data) return false;
    _accessToken = data.access_token;
    _user = data.user as AuthUser;
    _emit();
    return true;
  })().finally(() => {
    _refreshAndStoreInflight = null;
  });

  return _refreshAndStoreInflight;
}


/**
 * Logout — tells the server to blacklist the refresh token and clear
 * the cookie, then clears local in-memory state.
 */
export async function logout(): Promise<void> {
  clearAuth();
  await _refreshAndStoreInflight?.catch(() => false);
  await runExclusiveAuthAction(async () => {
    try {
      await fetch(LOGOUT_ENDPOINT, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
    } catch {
      // Ignore network errors — we still want to clear local state.
    }
  });
}


export async function switchRole(role: string): Promise<AuthUser> {
  if (!_accessToken) throw new Error('Authentication required');
  const response = await fetch(SWITCH_ROLE_ENDPOINT, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${_accessToken}`,
    },
    body: JSON.stringify({ role }),
  });
  if (!response.ok) throw new Error('Role switch failed');
  const data = await response.json();
  if (!data.access_token || !data.user) throw new Error('Invalid role switch response');
  setAuth(data.access_token, data.user);
  return data.user;
}


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
