import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: apiMocks }));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => {
      if (key === 'auth.password') return 'Password';
      if (key === 'auth.emailCode') return 'Email code';
      return key;
    },
  }),
}));

import LoginPage from '@/app/login/page';

describe('Telegram login capability', () => {
  beforeEach(() => {
    apiMocks.get.mockReset();
    apiMocks.post.mockReset();
  });

  it('hides the Telegram tab when the server reports the integration disabled', async () => {
    apiMocks.get.mockResolvedValue({ data: { telegram_login_enabled: false } });

    render(<LoginPage />);

    await waitFor(() => expect(apiMocks.get).toHaveBeenCalledWith('/v1/auth/capabilities'));
    expect(screen.queryByRole('button', { name: 'Telegram' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /password|пароль/i })).toBeInTheDocument();
  });

  it('shows the Telegram tab only when the server reports the integration enabled', async () => {
    apiMocks.get.mockResolvedValue({ data: { telegram_login_enabled: true } });

    render(<LoginPage />);

    expect(await screen.findByRole('tab', { name: 'Telegram' })).toBeInTheDocument();
  });
});
