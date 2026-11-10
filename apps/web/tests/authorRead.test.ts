import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ refreshSession: vi.fn() }));
vi.mock('@/lib/authRefreshCoordinator', () => ({
  refreshSession: mocks.refreshSession,
  runExclusiveAuthAction: async <T>(action: () => Promise<T>) => action(),
}));

import { clearAuth, getAccessToken, getCurrentUser, setAuth, type AuthUser } from '@/lib/auth';
import { authorRead } from '@/features/course-authoring/authorRead';
import { currentAuthorSession } from '@/features/course-authoring/authorSession';
import { useAuthStore } from '@/store/authStore';

const user: AuthUser = { user_id: 'author', tenant_id: 'tenant', role: 'methodologist', tenant: null,
  telegram_id: '', full_name: 'Author', email: null };
const replacement: AuthUser = { ...user, user_id: 'replacement', tenant_id: 'other-tenant' };
const response = (status: number) => ({ status, ok: status >= 200 && status < 300 } as Response);
const scope = () => currentAuthorSession(useAuthStore.getState());
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  mocks.refreshSession.mockReset();
  setAuth('expired', user);
});
afterEach(() => { vi.unstubAllGlobals(); clearAuth(); });

describe('authorRead', () => {
  it('refreshes one expired bearer and retries the GET under the same session', async () => {
    mocks.refreshSession.mockResolvedValue({ access_token: 'fresh', user });
    const fetchMock = vi.fn().mockResolvedValueOnce(response(401)).mockResolvedValueOnce(response(200));
    vi.stubGlobal('fetch', fetchMock);
    const original = scope();
    expect((await authorRead('/v1/courses/a', original)).status).toBe(200);
    expect(fetchMock.mock.calls).toEqual([
      ['/v1/courses/a', { method: 'GET', headers: { Authorization: 'Bearer expired' } }],
      ['/v1/courses/a', { method: 'GET', headers: { Authorization: 'Bearer fresh' } }],
    ]);
    expect(mocks.refreshSession).toHaveBeenCalledTimes(1);
    expect(scope()).toEqual(original);
  });

  it('shares the existing in-flight refresh for concurrent 401s', async () => {
    const refresh = deferred<{ access_token: string; user: AuthUser }>();
    mocks.refreshSession.mockReturnValue(refresh.promise);
    const fetchMock = vi.fn().mockResolvedValueOnce(response(401)).mockResolvedValueOnce(response(401))
      .mockResolvedValue(response(200));
    vi.stubGlobal('fetch', fetchMock);
    const original = scope();
    const reads = Promise.all([authorRead('/course', original), authorRead('/structure', original)]);
    await vi.waitFor(() => expect(mocks.refreshSession).toHaveBeenCalledTimes(1));
    refresh.resolve({ access_token: 'fresh', user });
    expect((await reads).map((item) => item.status)).toEqual([200, 200]);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('reuses the refreshed token when a sibling old-token 401 arrives after refresh finishes', async () => {
    mocks.refreshSession.mockResolvedValue({ access_token: 'fresh', user });
    const delayed = deferred<Response>();
    const calls = { '/course': 0, '/structure': 0 };
    const fetchMock = vi.fn((url: '/course' | '/structure', _options: RequestInit) => {
      calls[url] += 1;
      if (url === '/course') return Promise.resolve(response(calls[url] === 1 ? 401 : 200));
      return calls[url] === 1 ? delayed.promise : Promise.resolve(response(200));
    });
    vi.stubGlobal('fetch', fetchMock);
    const original = scope();
    const course = authorRead('/course', original);
    const structure = authorRead('/structure', original);
    expect((await course).status).toBe(200);
    expect(mocks.refreshSession).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toEqual({ method: 'GET', headers: { Authorization: 'Bearer expired' } });
    expect(fetchMock.mock.calls[1][1]).toEqual({ method: 'GET', headers: { Authorization: 'Bearer expired' } });
    delayed.resolve(response(401));
    expect((await structure).status).toBe(200);
    expect(mocks.refreshSession).toHaveBeenCalledTimes(1);
    expect(calls).toEqual({ '/course': 2, '/structure': 2 });
    expect(fetchMock.mock.calls[3][1]).toEqual({ method: 'GET', headers: { Authorization: 'Bearer fresh' } });
  });

  it('does not send another GET when refresh fails and clears the expired session', async () => {
    mocks.refreshSession.mockResolvedValue(null);
    const fetchMock = vi.fn().mockResolvedValue(response(401));
    vi.stubGlobal('fetch', fetchMock);
    await expect(authorRead('/course', scope())).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('refuses an old scope before the first dispatch', async () => {
    const original = scope();
    setAuth('replacement-token', replacement);
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    await expect(authorRead('/course', original)).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('does not refresh a 401 after the session changed while the first read was pending', async () => {
    const pending = deferred<Response>();
    const fetchMock = vi.fn().mockReturnValue(pending.promise); vi.stubGlobal('fetch', fetchMock);
    const result = authorRead('/course', scope());
    setAuth('replacement-token', replacement);
    pending.resolve(response(401));
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
    expect(mocks.refreshSession).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe('replacement-token');
  });

  it('does not retry or clear a replacement session when it changes during refresh', async () => {
    const refresh = deferred<{ access_token: string; user: AuthUser }>();
    mocks.refreshSession.mockReturnValue(refresh.promise);
    const fetchMock = vi.fn().mockResolvedValue(response(401)); vi.stubGlobal('fetch', fetchMock);
    const result = authorRead('/course', scope());
    await vi.waitFor(() => expect(mocks.refreshSession).toHaveBeenCalledTimes(1));
    setAuth('replacement-token', replacement);
    refresh.resolve({ access_token: 'fresh', user });
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getCurrentUser()?.user_id).toBe('replacement');
    expect(getAccessToken()).toBe('replacement-token');
  });

  it.each([
    ['impersonated_by', 'platform-admin'],
    ['impersonated_role', 'superadmin'],
  ] as const)('does not refresh an impersonated session with %s after 401', async (field, value) => {
    const impersonated = { ...user, [field]: value };
    setAuth('impersonated-token', impersonated);
    const before = scope();
    const beforeEpoch = useAuthStore.getState().sessionEpoch;
    const fetchMock = vi.fn().mockResolvedValue(response(401)); vi.stubGlobal('fetch', fetchMock);
    expect((await authorRead('/course', before)).status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/course', { method: 'GET', headers: { Authorization: 'Bearer impersonated-token' } });
    expect(mocks.refreshSession).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe('impersonated-token');
    expect(useAuthStore.getState().accessToken).toBe('impersonated-token');
    expect(getCurrentUser()).toEqual(impersonated);
    expect(useAuthStore.getState().user).toEqual(impersonated);
    expect(useAuthStore.getState().sessionEpoch).toBe(beforeEpoch);
    expect(scope()).toEqual(before);
  });

  it('rejects an unexpected impersonation identity returned while refreshing an ordinary session', async () => {
    mocks.refreshSession.mockResolvedValue({ access_token: 'fresh', user: { ...user, impersonated_by: 'other-admin' } });
    const fetchMock = vi.fn().mockResolvedValue(response(401)); vi.stubGlobal('fetch', fetchMock);
    await expect(authorRead('/course', scope())).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('suppresses the retried response if the session changes while it is pending', async () => {
    mocks.refreshSession.mockResolvedValue({ access_token: 'fresh', user });
    const pending = deferred<Response>();
    const fetchMock = vi.fn().mockResolvedValueOnce(response(401)).mockReturnValueOnce(pending.promise);
    vi.stubGlobal('fetch', fetchMock);
    const result = authorRead('/course', scope());
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    setAuth('replacement-token', replacement);
    pending.resolve(response(200));
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
    expect(getAccessToken()).toBe('replacement-token');
  });

  it('returns a second 401 without another refresh or retry', async () => {
    mocks.refreshSession.mockResolvedValue({ access_token: 'fresh', user });
    const fetchMock = vi.fn().mockResolvedValue(response(401)); vi.stubGlobal('fetch', fetchMock);
    expect((await authorRead('/course', scope())).status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(mocks.refreshSession).toHaveBeenCalledTimes(1);
  });

  it('suppresses a completed response if the session changes before it arrives', async () => {
    const pending = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending.promise));
    const result = authorRead('/course', scope());
    setAuth('replacement-token', replacement);
    pending.resolve(response(200));
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
  });

  it.each([403, 500])('does not refresh or retry HTTP %i', async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(response(status)); vi.stubGlobal('fetch', fetchMock);
    expect((await authorRead('/course', scope())).status).toBe(status);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mocks.refreshSession).not.toHaveBeenCalled();
  });

  it('does not retry a network failure with unknown outcome', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network'));
    vi.stubGlobal('fetch', fetchMock);
    await expect(authorRead('/course', scope())).rejects.toThrow('network');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mocks.refreshSession).not.toHaveBeenCalled();
  });
});
