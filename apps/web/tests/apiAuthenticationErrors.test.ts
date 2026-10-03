import { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  clearStoredAuth: vi.fn(),
  getAccessToken: vi.fn<() => string | null>(() => null),
  forceRefreshAndStoreSession: vi.fn<() => Promise<boolean>>(),
  setAuth: vi.fn(),
}));

vi.mock('@/lib/auth', () => ({
  ...authMocks,
}));

import { api, isPublicAuthenticationRequest } from '@/lib/api';

describe('API authentication error handling', () => {
  const originalAdapter = api.defaults.adapter;

  beforeEach(() => {
    authMocks.clearStoredAuth.mockReset();
    authMocks.getAccessToken.mockReturnValue(null);
    authMocks.forceRefreshAndStoreSession.mockReset();
    authMocks.setAuth.mockReset();
    vi.stubGlobal('fetch', vi.fn());
    api.defaults.adapter = async (config) => {
      throw new AxiosError(
        'Unauthorized',
        'ERR_BAD_REQUEST',
        config as InternalAxiosRequestConfig,
        undefined,
        {
          data: { detail: 'Неверный или просроченный код' },
          status: 401,
          statusText: 'Unauthorized',
          headers: {},
          config: config as InternalAxiosRequestConfig,
        },
      );
    };
  });

  afterEach(() => {
    api.defaults.adapter = originalAdapter;
    vi.unstubAllGlobals();
  });

  it('classifies email and invitation OTP routes as public authentication requests', () => {
    expect(isPublicAuthenticationRequest('/v1/auth/email/verify-code')).toBe(true);
    expect(isPublicAuthenticationRequest('/v1/invitations/token/accept')).toBe(true);
    expect(isPublicAuthenticationRequest('/v1/kiosks/public-token/identify')).toBe(true);
    expect(isPublicAuthenticationRequest('/v1/courses')).toBe(false);
    expect(isPublicAuthenticationRequest('/v1/users/invitations')).toBe(false);
  });

  it('keeps the invitation page open when OTP verification returns 401', async () => {
    await expect(
      api.post('/v1/invitations/invite-token/accept', { code: '123456' }),
    ).rejects.toMatchObject({ response: { status: 401 } });

    expect(fetch).not.toHaveBeenCalled();
    expect(authMocks.clearStoredAuth).not.toHaveBeenCalled();
    expect(authMocks.forceRefreshAndStoreSession).not.toHaveBeenCalled();
  });

  it.each([
    { url: '/v1/admin/super/tenants?limit=10', method: 'get', data: undefined },
    { url: '/v1/admin/super/tenants/synthetic-tenant', method: 'get', data: undefined },
    { url: '/v1/admin/provider-keys', method: 'get', data: undefined },
    { url: '/v1/admin/model-routing', method: 'get', data: undefined },
    { url: '/v1/admin/super/operations/summary', method: 'get', data: undefined },
    { url: '/v1/admin/super/tenants/synthetic-tenant/impersonate', method: 'post', data: { role: 'admin' } },
    { url: '/v1/admin/super/operations/cleanup-synthetic', method: 'post', data: { dry_run: true, min_age_hours: 24 } },
    { url: '/v1/admin/super/operations/recover-stale-ai-jobs', method: 'post', data: { dry_run: true, min_age_hours: 24 } },
    { url: '/v1/admin/super/operations/requeue-failed-crm-leads', method: 'post', data: { dry_run: true, limit: 20 } },
  ])('replays $url once with the refreshed session token after expiry', async ({ url, method, data }) => {
    const expiredAdapter = api.defaults.adapter as (config: InternalAxiosRequestConfig) => Promise<never>;
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      if (adapter.mock.calls.length === 1) return expiredAdapter(config);
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
    });
    api.defaults.adapter = adapter;
    authMocks.getAccessToken.mockReturnValue('expired-synthetic-token');
    authMocks.forceRefreshAndStoreSession.mockImplementation(async () => {
      authMocks.getAccessToken.mockReturnValue('refreshed-synthetic-token');
      return true;
    });

    await expect(api.request({ url, method, data })).resolves.toMatchObject({ status: 200, data: { ok: true } });

    expect(adapter).toHaveBeenCalledTimes(2);
    expect(authMocks.forceRefreshAndStoreSession).toHaveBeenCalledTimes(1);
    expect(adapter.mock.calls[1][0].url).toBe(url);
    expect(adapter.mock.calls[1][0].method).toBe(method);
    if (data) expect(JSON.parse(adapter.mock.calls[1][0].data)).toEqual(data);
    expect(adapter.mock.calls[1][0].withCredentials).toBe(true);
    expect(adapter.mock.calls[1][0].headers.get('Authorization')).toBe('Bearer refreshed-synthetic-token');
    expect(authMocks.clearStoredAuth).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
});
