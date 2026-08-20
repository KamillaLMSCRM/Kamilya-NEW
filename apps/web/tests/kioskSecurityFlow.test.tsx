import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const setAuth = vi.hoisted(() => vi.fn());

vi.mock('next/navigation', () => ({ useParams: () => ({ token: 'public-kiosk-token' }) }));
vi.mock('@/lib/api', () => ({ api: { get: apiGet, post: apiPost } }));
vi.mock('@/lib/auth', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/auth')>(),
  setAuth,
  getStoredAuth: () => null,
}));
vi.mock('@/lib/useIdleTimeout', () => ({ useIdleTimeout: () => ({ warningSeconds: null }) }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: (key: string) => key }) }));
vi.mock('@/components/ui/Toast', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import KioskPage from '@/app/kiosk/[token]/page';
import AdminKiosksPage from '@/app/admin/kiosks/page';
import { useAuthStore } from '@/store/authStore';

describe('secure kiosk identification', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiGet.mockResolvedValue({
      data: {
        name: 'Киоск Павлодар',
        tenant_name: 'Ломбард Сандык',
        scope_position_name: null,
        location: 'Филиал Павлодар',
        valid: true,
        reason_if_invalid: null,
      },
    });
    apiPost.mockResolvedValue({
      data: {
        user: {
          user_id: 'user-1',
          first_name: 'Алия',
          last_name: 'Садыкова',
          personnel_number: 'EMP-1042',
          position_name: 'Кассир',
        },
        kiosk_name: 'Киоск Павлодар',
        kiosk_location: 'Филиал Павлодар',
        courses: [],
        access_token: 'kiosk-access-token',
        token_type: 'bearer',
      },
    });
  });

  it('requires a six-digit PIN and sends it with the personnel identifier', async () => {
    render(<KioskPage />);

    const personnel = await screen.findByLabelText('Табельный номер');
    const pin = screen.getByLabelText('PIN для киоска');
    const submit = screen.getByRole('button', { name: 'Показать курсы' });
    expect(submit).toBeDisabled();

    fireEvent.change(personnel, { target: { value: 'EMP-1042' } });
    fireEvent.change(pin, { target: { value: '384921' } });
    fireEvent.click(submit);

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(
      '/v1/kiosks/public-kiosk-token/identify',
      { personnel_number: 'EMP-1042', pin: '384921' },
    ));
    expect(setAuth).toHaveBeenCalledWith('kiosk-access-token', expect.objectContaining({ role: 'student' }));
  });

  it('lets an administrator issue a one-time PIN for an eligible learner', async () => {
    useAuthStore.setState({
      accessToken: 'admin-token',
      user: { id: 'admin-1', role: 'admin' } as never,
      initialized: true,
    });
    apiGet.mockImplementation(async (url: string) => {
      if (url === '/v1/admin/kiosks') return { data: [] };
      if (url === '/v1/admin/kiosks/scope-positions') return { data: [] };
      if (url.startsWith('/v1/admin/kiosks/access-logs')) return { data: [] };
      if (url === '/v1/admin/kiosks/pin-users') {
        return {
          data: [{
            user_id: 'user-1',
            full_name: 'Садыкова Алия',
            personnel_number_masked: '******42',
            has_kiosk_pin: false,
          }],
        };
      }
      throw new Error(`Unexpected GET ${url}`);
    });
    apiPost.mockResolvedValue({
      data: {
        user_id: 'user-1',
        personnel_number_masked: '******42',
        temporary_pin: '384921',
        issued_at: '2026-08-20T12:00:00Z',
      },
    });

    render(<AdminKiosksPage />);

    const selector = await screen.findByLabelText('Сотрудник для PIN');
    fireEvent.change(selector, { target: { value: 'user-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Выпустить PIN' }));

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(
      '/v1/admin/kiosks/pin-users/user-1/issue',
    ));
    expect(await screen.findByText('384921')).toBeInTheDocument();
    expect(screen.getByText('Скопируйте PIN сейчас')).toBeInTheDocument();
  });
});
