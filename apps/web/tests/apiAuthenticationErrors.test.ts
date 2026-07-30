import { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  clearStoredAuth: vi.fn(),
  getAccessToken: vi.fn(() => null),
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
    expect(isPublicAuthenticationRequest('/v1/courses')).toBe(false);
    expect(isPublicAuthenticationRequest('/v1/users/invitations')).toBe(false);
  });

  it('keeps the invitation page open when OTP verification returns 401', async () => {
    await expect(
      api.post('/v1/invitations/invite-token/accept', { code: '123456' }),
    ).rejects.toMatchObject({ response: { status: 401 } });

    expect(fetch).not.toHaveBeenCalled();
    expect(authMocks.clearStoredAuth).not.toHaveBeenCalled();
  });
});
