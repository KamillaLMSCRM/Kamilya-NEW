import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getAccessTokenExpiryMs,
  getSessionExpiryMs,
  startSessionDeadlineGuard,
} from '@/lib/sessionDeadline';

function token(payload: Record<string, unknown>): string {
  const encode = (value: unknown) => btoa(JSON.stringify(value))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  return `${encode({ alg: 'none' })}.${encode(payload)}.signature`;
}

afterEach(() => vi.useRealTimers());

describe('browser session deadline', () => {
  it('reads session and access deadlines without treating the JWT as authorization evidence', () => {
    const accessToken = token({ exp: 120, session_exp: 240 });
    expect(getAccessTokenExpiryMs(accessToken)).toBe(120_000);
    expect(getSessionExpiryMs(accessToken)).toBe(240_000);
    expect(getSessionExpiryMs('not-a-jwt')).toBeNull();
  });

  it('closes a new browser session exactly at its absolute deadline', () => {
    vi.useFakeTimers();
    const onExpired = vi.fn();
    const revalidate = vi.fn();
    const stop = startSessionDeadlineGuard({
      accessToken: token({ exp: 2_000, session_exp: 1_100 }),
      now: () => 1_000_000,
      onExpired,
      revalidateLegacySession: revalidate,
    });

    vi.advanceTimersByTime(99_999);
    expect(onExpired).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onExpired).toHaveBeenCalledOnce();
    expect(revalidate).not.toHaveBeenCalled();
    stop();
  });

  it('immediately closes a token whose absolute deadline has passed', () => {
    const onExpired = vi.fn();
    startSessionDeadlineGuard({
      accessToken: token({ session_exp: 999 }),
      now: () => 1_000_000,
      onExpired,
      revalidateLegacySession: vi.fn(),
    });
    expect(onExpired).toHaveBeenCalledOnce();
  });

  it('revalidates a legacy token just after access-token expiry', async () => {
    vi.useFakeTimers();
    const revalidate = vi.fn().mockResolvedValue(undefined);
    const stop = startSessionDeadlineGuard({
      accessToken: token({ exp: 1_010 }),
      now: () => 1_000_000,
      onExpired: vi.fn(),
      revalidateLegacySession: revalidate,
    });

    await vi.advanceTimersByTimeAsync(10_249);
    expect(revalidate).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(revalidate).toHaveBeenCalledOnce();
    stop();
  });

  it('cancels an old deadline when the token is replaced or the user logs out', () => {
    vi.useFakeTimers();
    const onExpired = vi.fn();
    const stop = startSessionDeadlineGuard({
      accessToken: token({ session_exp: 1_100 }),
      now: () => 1_000_000,
      onExpired,
      revalidateLegacySession: vi.fn(),
    });
    stop();
    vi.advanceTimersByTime(100_000);
    expect(onExpired).not.toHaveBeenCalled();
  });
});
