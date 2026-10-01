import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  login: vi.fn(), replace: vi.fn(),
  exclusive: vi.fn(async (callback: () => Promise<unknown>) => callback()),
}));
vi.mock('next/navigation', () => ({
  useParams: () => ({ token: 'synthetic-opaque-link' }),
  useRouter: () => ({ replace: mocks.replace }),
  usePathname: () => '/access/synthetic-opaque-link',
}));
vi.mock('@/store/authStore', () => ({ useAuthStore: () => mocks.login }));
vi.mock('@/lib/authRefreshCoordinator', () => ({ runExclusiveAuthAction: mocks.exclusive }));
vi.mock('@/components/legal/PublicLegalFooter', () => ({ PublicLegalFooter: () => null }));
vi.mock('@/components/brand/Logo', () => ({ Logo: () => null }));
vi.mock('@/components/LanguageSwitcher', () => ({ LanguageSwitcher: () => null }));
import AssignmentAccessPage from '@/app/access/[token]/page';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('assignment entry browser session', () => {
  it('includes browser credentials and serializes PIN entry with ordinary refresh', async () => {
    const student = { role: 'student', roles: ['student'], user_id: 'synthetic-learner' };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ access_token: 'fixed-expiry-jwt', user: student, assigned_course_id: 'synthetic-course' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<AssignmentAccessPage />);
    fireEvent.change(screen.getByLabelText('PIN'), { target: { value: '123456' } });
    fireEvent.submit(screen.getByLabelText('PIN').closest('form')!);
    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith('fixed-expiry-jwt', student));
    expect(mocks.exclusive).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/assignment-access/synthetic-opaque-link/exchange'), {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{"pin":"123456"}',
    });
    expect(mocks.replace).toHaveBeenCalledWith('/courses/synthetic-course');
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(sessionStorage.getItem('access_token')).toBeNull();
  });

  it('does not replace identity or navigate when PIN exchange fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    render(<AssignmentAccessPage />);
    fireEvent.change(screen.getByLabelText('PIN'), { target: { value: '123456' } });
    fireEvent.submit(screen.getByLabelText('PIN').closest('form')!);
    await screen.findByRole('alert');
    expect(mocks.login).not.toHaveBeenCalled();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});
