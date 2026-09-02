import { describe, expect, it, vi } from 'vitest';
import type { AuthUser } from '@/lib/auth';
import {
  createRefreshCoordinator,
  type RefreshLock,
  type RefreshResponseLike,
} from '@/lib/authRefreshCoordinator';

const user: AuthUser = {
  user_id: 'user-1',
  tenant_id: 'tenant-1',
  tenant: { id: 'tenant-1', name: 'Test tenant' },
  telegram_id: 'telegram-1',
  role: 'methodologist',
  full_name: 'Test User',
  email: 'test@example.com',
};

function response(status: number, payload?: unknown): RefreshResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

function queuedLock(): RefreshLock {
  let tail = Promise.resolve();
  return async <T>(callback: () => Promise<T>) => {
    const previous = tail;
    let release!: () => void;
    tail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      return await callback();
    } finally {
      release();
    }
  };
}

describe('auth refresh coordinator', () => {
  it('serializes independent tab refreshes around the shared cookie', async () => {
    let cookieVersion = 0;
    let activeRequests = 0;
    let maximumActiveRequests = 0;

    const request = async () => {
      activeRequests += 1;
      maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
      const requestCookie = cookieVersion;
      await Promise.resolve();
      if (requestCookie === cookieVersion) cookieVersion += 1;
      activeRequests -= 1;
      return response(200, { access_token: `access-${cookieVersion}`, user });
    };
    const lock = queuedLock();
    const tabA = createRefreshCoordinator(request, lock);
    const tabB = createRefreshCoordinator(request, lock);

    const results = await Promise.all([tabA.refresh(), tabB.refresh()]);

    expect(maximumActiveRequests).toBe(1);
    expect(results.every(Boolean)).toBe(true);
    expect(cookieVersion).toBe(2);
  });

  it('retries one refresh 401 and then succeeds', async () => {
    let calls = 0;
    const coordinator = createRefreshCoordinator(async () => {
      calls += 1;
      return calls === 1
        ? response(401)
        : response(200, { access_token: 'access-2', user });
    }, queuedLock());

    await expect(coordinator.refresh()).resolves.toMatchObject({ access_token: 'access-2' });
    expect(calls).toBe(2);
  });

  it('does not retry a genuinely invalid session indefinitely', async () => {
    let calls = 0;
    const coordinator = createRefreshCoordinator(async () => {
      calls += 1;
      return response(401);
    }, queuedLock());

    await expect(coordinator.refresh()).resolves.toBeNull();
    expect(calls).toBe(2);
  });

  it('waits for an active refresh before running an exclusive auth action', async () => {
    let releaseRefresh!: () => void;
    const refreshFinished = new Promise<void>((resolve) => {
      releaseRefresh = resolve;
    });
    const events: string[] = [];
    const coordinator = createRefreshCoordinator(async () => {
      events.push('refresh-start');
      await refreshFinished;
      events.push('refresh-end');
      return response(200, { access_token: 'access-1', user });
    }, queuedLock());

    const refresh = coordinator.refresh();
    const exclusiveAction = coordinator.runExclusive(async () => {
      events.push('logout');
    });

    await Promise.resolve();
    expect(events).toEqual(['refresh-start']);
    releaseRefresh();
    await Promise.all([refresh, exclusiveAction]);

    expect(events).toEqual(['refresh-start', 'refresh-end', 'logout']);
  });

  it('shares one applied result between startup restore and API recovery', async () => {
    vi.resetModules();
    let resolveRefresh!: (value: unknown) => void;
    const refreshResult = new Promise<unknown>((resolve) => {
      resolveRefresh = resolve;
    });
    const refreshSession = async () => refreshResult as any;
    vi.doMock('@/lib/authRefreshCoordinator', () => ({ refreshSession }));

    const auth = await import('@/lib/auth');
    const startupRestore = auth.restoreSession();
    const apiRecovery = auth.refreshAndStoreSession();
    resolveRefresh({ access_token: 'access-shared', user });

    await expect(Promise.all([startupRestore, apiRecovery])).resolves.toEqual([true, true]);
    expect(auth.getAccessToken()).toBe('access-shared');
    vi.doUnmock('@/lib/authRefreshCoordinator');
  });

  it('forces recovery past a stale access token and stores the refreshed token', async () => {
    vi.resetModules();
    const refreshSession = vi.fn().mockResolvedValue({
      access_token: 'access-fresh',
      user,
    });
    vi.doMock('@/lib/authRefreshCoordinator', () => ({ refreshSession }));

    const auth = await import('@/lib/auth');
    auth.setAuth('access-stale', user);

    await expect(auth.forceRefreshAndStoreSession()).resolves.toBe(true);

    expect(refreshSession).toHaveBeenCalledTimes(1);
    expect(auth.getAccessToken()).toBe('access-fresh');
    vi.doUnmock('@/lib/authRefreshCoordinator');
  });
});
