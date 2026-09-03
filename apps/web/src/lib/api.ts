import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import {
  getAccessToken,
  clearStoredAuth,
  forceRefreshAndStoreSession,
} from '@/lib/auth';
import { getAuthenticationEntry } from '@/lib/rolePolicy';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,  // send httpOnly refresh cookie with every request
});

api.interceptors.request.use((config) => {
  const reviewAccess = isReviewAccessRequest(config.url);
  const scopedReview = isScopedReviewRequest(config.url);
  if (reviewAccess) {
    if (config.headers) delete config.headers.Authorization;
    return config;
  }
  if (scopedReview) {
    // reviewConfig supplies the capability explicitly; never replace it with
    // the signed-in learner/admin token and never inject that token by default.
    const explicitAuthorization = config.headers?.get?.('Authorization') ?? config.headers?.Authorization;
    if (!explicitAuthorization && config.headers) delete config.headers.Authorization;
    return config;
  }
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function isPublicAuthenticationRequest(url?: string): boolean {
  if (!url) return false;
  const normalized = url.toLowerCase();
  return normalized.includes('/auth/')
    || normalized.includes('/v1/invitations/')
    || (normalized.includes('/v1/kiosks/') && normalized.endsWith('/identify'));
}

/** Review capabilities must stay on their purpose-bound endpoints. */
export function isReviewAccessRequest(url?: string): boolean {
  return typeof url === 'string' && url.toLowerCase().includes('/v1/course-review-access/');
}

export function isScopedReviewRequest(url?: string): boolean {
  if (typeof url !== 'string') return false;
  const normalized = url.toLowerCase();
  return normalized.includes('/v1/course-review-requests')
    || normalized.includes('/v1/course-review-attempts')
    || /\/v1\/course-approval-requests\/[^/]+\/attempts(?:$|[?#])/.test(normalized);
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
    const reviewRequest = isReviewAccessRequest(original?.url) || isScopedReviewRequest(original?.url);
    if (status === 401 && original && !original._retried && !reviewRequest) {
      const isPublicAuthEndpoint = isPublicAuthenticationRequest(original.url);
      if (!isPublicAuthEndpoint) {
        original._retried = true;
        const ok = await forceRefreshAndStoreSession();
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

    if (status === 401 && !isPublicAuthenticationRequest(original?.url) && !reviewRequest) {
      clearStoredAuth();
      if (typeof window !== 'undefined') {
        window.location.href = getAuthenticationEntry(window.location.pathname);
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
