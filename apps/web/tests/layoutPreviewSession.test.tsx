import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Layout from '@/components/layout/Layout';
import { api } from '@/lib/api';

const state = vi.hoisted(() => ({
  accessToken: '', initialized: true,
  user: { role: 'methodologist', impersonated_by: undefined as string | undefined },
  initialize: vi.fn(), logout: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }), usePathname: () => '/documents' }));
vi.mock('@/store/authStore', () => ({ useAuthStore: () => state }));
vi.mock('@/lib/auth', () => ({ getAccessToken: () => state.accessToken }));
vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }));
vi.mock('@/components/layout/Sidebar', () => ({ default: () => null }));
vi.mock('@/components/layout/TopBar', () => ({ default: () => null }));
vi.mock('@/components/CommandPalette', () => ({ default: () => null }));
vi.mock('@/components/demo/DemoBanner', () => ({ DemoBanner: () => null }));
vi.mock('@/components/demo/DemoLimitProvider', () => ({ DemoLimitProvider: ({ children }: { children: React.ReactNode }) => children }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  const deadline = Math.floor(Date.now() / 1000) + 60;
  state.accessToken = `header.${btoa(JSON.stringify({ exp: deadline, session_exp: deadline }))}.signature`;
  state.user.impersonated_by = undefined;
  vi.mocked(api.get).mockResolvedValue({ data: {} });
  localStorage.clear();
});
afterEach(() => vi.useRealTimers());

describe('layout session validation during tenant preview', () => {
  it('does not request the forbidden platform profile on focus or visibility return', () => {
    state.user.impersonated_by = 'platform-operator';
    render(<Layout>Test cabinet</Layout>);
    act(() => { window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange')); });
    expect(api.get).not.toHaveBeenCalledWith('/v1/users/me');
  });

  it('retains normal profile revalidation outside preview', () => {
    render(<Layout>Test cabinet</Layout>);
    act(() => window.dispatchEvent(new Event('focus')));
    expect(api.get).toHaveBeenCalledWith('/v1/users/me');
  });

  it('still expires a preview at its original absolute session deadline', async () => {
    state.user.impersonated_by = 'platform-operator';
    render(<Layout>Test cabinet</Layout>);
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(state.logout).toHaveBeenCalledOnce();
  });
});
