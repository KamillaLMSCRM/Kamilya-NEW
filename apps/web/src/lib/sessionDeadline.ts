const LEGACY_REVALIDATE_INTERVAL_MS = 15 * 60 * 1000;
const TOKEN_EXPIRY_SKEW_MS = 250;

type JwtPayload = Record<string, unknown>;

function decodeJwtPayload(token: string): JwtPayload | null {
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
    return JSON.parse(atob(padded)) as JwtPayload;
  } catch {
    return null;
  }
}

function numericDateMs(token: string, claim: string): number | null {
  const value = decodeJwtPayload(token)?.[claim];
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? value * 1000
    : null;
}

export function getSessionExpiryMs(token: string): number | null {
  return numericDateMs(token, 'session_exp');
}

export function getAccessTokenExpiryMs(token: string): number | null {
  return numericDateMs(token, 'exp');
}

interface SessionDeadlineGuardOptions {
  accessToken: string;
  now?: () => number;
  onExpired: () => void;
  revalidateLegacySession: () => Promise<unknown>;
  setTimer?: typeof setTimeout;
  clearTimer?: typeof clearTimeout;
}

/**
 * Keep an already-rendered browser session aligned with the server's absolute
 * login deadline. New tokens carry session_exp and close exactly on time.
 * Tokens issued before this rollout are revalidated when their short-lived
 * access credential expires, then replaced by a token with session_exp.
 */
export function startSessionDeadlineGuard(options: SessionDeadlineGuardOptions): () => void {
  const now = options.now ?? Date.now;
  const setTimer = options.setTimer ?? setTimeout;
  const clearTimer = options.clearTimer ?? clearTimeout;
  const sessionExpiry = getSessionExpiryMs(options.accessToken);
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  if (sessionExpiry !== null) {
    const delay = sessionExpiry - now();
    if (delay <= 0) {
      options.onExpired();
      return () => undefined;
    }
    timer = setTimer(options.onExpired, delay);
  } else {
    const accessExpiry = getAccessTokenExpiryMs(options.accessToken);
    const untilAccessExpiry = accessExpiry === null
      ? LEGACY_REVALIDATE_INTERVAL_MS
      : Math.max(0, accessExpiry - now() + TOKEN_EXPIRY_SKEW_MS);
    const firstDelay = Math.min(untilAccessExpiry, LEGACY_REVALIDATE_INTERVAL_MS);

    const revalidate = async () => {
      try {
        await options.revalidateLegacySession();
      } catch {
        // Connectivity failures are not proof that the server session ended.
      } finally {
        // Usually revalidation rotates the token and the React effect disposes
        // this guard. Re-arm only as a safe fallback for unusual legacy tokens.
        if (!disposed) timer = setTimer(revalidate, LEGACY_REVALIDATE_INTERVAL_MS);
      }
    };
    timer = setTimer(revalidate, firstDelay);
  }

  return () => {
    disposed = true;
    if (timer !== undefined) clearTimer(timer);
  };
}
