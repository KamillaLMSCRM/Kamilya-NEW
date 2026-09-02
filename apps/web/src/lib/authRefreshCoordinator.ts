export interface RefreshPayload {
  access_token: string;
  user: unknown;
}

export interface RefreshResponseLike {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

export type RefreshRequest = () => Promise<RefreshResponseLike>;
export type RefreshLock = <T>(callback: () => Promise<T>) => Promise<T>;

const LOCK_NAME = 'kamilya-auth-refresh';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

let fallbackQueue = Promise.resolve();

async function withSameTabLock<T>(callback: () => Promise<T>): Promise<T> {
  const previous = fallbackQueue;
  let release!: () => void;
  fallbackQueue = new Promise<void>((resolve) => {
    release = resolve;
  });

  await previous;
  try {
    return await callback();
  } finally {
    release();
  }
}

export function getDefaultRefreshLock(): RefreshLock {
  if (typeof navigator !== 'undefined') {
    const lockManager = (navigator as Navigator & {
      locks?: { request: <T>(name: string, callback: () => Promise<T>) => Promise<T> };
    }).locks;
    if (lockManager?.request) {
      return async <T>(callback: () => Promise<T>) =>
        await lockManager.request(LOCK_NAME, callback);
    }
  }
  return withSameTabLock;
}

export function createRefreshCoordinator(
  request: RefreshRequest,
  lock: RefreshLock = getDefaultRefreshLock(),
) {
  let inFlight: Promise<RefreshPayload | null> | null = null;

  const refresh = (): Promise<RefreshPayload | null> => {
    if (inFlight) return inFlight;

    inFlight = lock(async () => {
      // A 401 can mean that another client rotated the shared cookie just
      // before this request was accepted. Retry once after serialization;
      // never keep retrying an actually invalid session.
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const response = await request();
          if (response.ok) {
            const payload = await response.json() as Partial<RefreshPayload>;
            if (payload.access_token && payload.user) {
              return payload as RefreshPayload;
            }
            return null;
          }
          if (response.status !== 401 || attempt === 1) return null;
        } catch {
          return null;
        }
      }
      return null;
    }).finally(() => {
      inFlight = null;
    });

    return inFlight;
  };

  const runExclusive = async <T>(callback: () => Promise<T>): Promise<T> => {
    await inFlight?.catch(() => null);
    return lock(callback);
  };

  return { refresh, runExclusive };
}

const defaultCoordinator = createRefreshCoordinator(async () => fetch(
  `${API_BASE_URL}/v1/auth/refresh`,
  {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  },
));

export function refreshSession(): Promise<RefreshPayload | null> {
  return defaultCoordinator.refresh();
}

export function runExclusiveAuthAction<T>(callback: () => Promise<T>): Promise<T> {
  return defaultCoordinator.runExclusive(callback);
}
