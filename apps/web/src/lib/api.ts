import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import {
  getAccessToken,
  clearStoredAuth,
  restoreSession,
  setAuth,
  AuthUser,
} from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,  // send httpOnly refresh cookie with every request
});

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Track in-flight refresh so we don't fan out N refresh requests when
// N components fire 401s in parallel. The first request triggers the
// refresh; all other 401s in the same tick await the same promise.
let _refreshInFlight: Promise<boolean> | null = null;

async function _refresh(): Promise<boolean> {
  if (_refreshInFlight) return _refreshInFlight;
  _refreshInFlight = (async () => {
    try {
      const r = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!r.ok) return false;
      const data = await r.json();
      if (data.access_token && data.user) {
        setAuth(data.access_token, data.user as AuthUser);
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      _refreshInFlight = null;
    }
  })();
  return _refreshInFlight;
}

api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const status = err.response?.status;
    const original = err.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;

    // Refresh-on-401: any 401 from a real API call (not the refresh endpoint
    // itself) means the access token expired or was never sent. Try to
    // mint a new one via the httpOnly refresh cookie. If that succeeds,
    // retry the original request. If it fails, log the user out.
    //
    // This is the fix for the 2026-06-29 login-bounce bug where the
    // dashboard's first /api/v1/courses call returned 401 (no cookie /
    // no token) and the OLD interceptor immediately redirected to /login
    // without ever attempting to refresh the session.
    if (status === 401 && original && !original._retried) {
      const isAuthEndpoint = original.url?.includes('/auth/refresh')
        || original.url?.includes('/auth/login')
        || original.url?.includes('/auth/superadmin-login')
        || original.url?.includes('/auth/check-code')
        || original.url?.includes('/auth/demo-login')
        || original.url?.includes('/auth/logout');
      if (!isAuthEndpoint) {
        original._retried = true;
        const ok = await _refresh();
        if (ok) {
          // Replay the original request with the fresh token.
          const token = getAccessToken();
          if (token) {
            original.headers = original.headers ?? ({} as any);
            (original.headers as any).Authorization = `Bearer ${token}`;
          }
          try {
            return await api(original);
          } catch {
            // Fall through to the redirect-on-auth-failure branch below.
          }
        }
      }
    }

    if (status === 401) {
      clearStoredAuth();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
    }
    // Demo sandbox limits — surface a global event so DemoLimitProvider
    // can pop the friendly modal regardless of which component fired
    // the request.
    if (
      status === 403 &&
      err.response?.data &&
      (err.response.data as any).detail?.code === 'demo_limit_exceeded'
    ) {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('demo_limit', { detail: (err.response.data as any).detail })
        );
      }
    }
    return Promise.reject(err);
  },
);

export default api;
