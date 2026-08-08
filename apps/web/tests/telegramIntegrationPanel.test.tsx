import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import IntegrationsPage from '@/app/admin/settings/integrations/page';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/features/integrations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/integrations/api')>();
  return {
    ...actual,
    listIntegrations: vi.fn().mockResolvedValue([
      {
        channel: 'telegram',
        is_active: true,
        last_test_at: null,
        last_test_status: null,
        has_secret: true,
        updated_at: '2026-08-08T00:00:00Z',
        extra: {},
      },
    ]),
    getWhatsAppStatus: vi.fn().mockResolvedValue({
      status: 'not_started',
      phone_number: null,
      qr: null,
      qr_expires_at: null,
    }),
  };
});

describe('Telegram integration saved-token state', () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: 'test-token' });
  });

  it('shows that the secret is stored and disables save until a replacement is entered', async () => {
    render(<IntegrationsPage />);

    fireEvent.click(await screen.findByRole('button', { name: /Telegram/i }));

    expect(screen.getByText('Токен сохранён. Введите новый токен только для замены.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Проверить токен' })).toBeEnabled();
  });
});
