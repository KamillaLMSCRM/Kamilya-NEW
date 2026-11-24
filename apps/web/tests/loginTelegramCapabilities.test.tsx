import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
    expect(screen.queryByRole('tab', { name: 'Telegram' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /password|пароль/i })).toBeInTheDocument();
  });

  it('supports keyboard navigation across the available methods without submitting', async () => {
    apiMocks.get.mockResolvedValue({ data: { telegram_login_enabled: true } });
    render(<LoginPage />);

    const email = screen.getByRole('tab', { name: 'Email code' });
    const password = screen.getByRole('tab', { name: 'Password' });
    const telegram = await screen.findByRole('tab', { name: 'Telegram' });
    expect(email).toHaveAttribute('tabindex', '0');
    expect(password).toHaveAttribute('tabindex', '-1');

    email.focus();
    const navigate = (from: HTMLElement, key: string, to: HTMLElement) => {
      fireEvent.keyDown(from, { key });
      expect(to).toHaveFocus();
      expect(to).toHaveAttribute('aria-selected', 'true');
      expect(to).toHaveAttribute('tabindex', '0');
      expect(screen.getByRole('tabpanel')).toHaveAttribute('id', to.getAttribute('aria-controls'));
      expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', to.id);
    };
    navigate(email, 'ArrowRight', password);
    navigate(password, 'End', telegram);
    navigate(telegram, 'ArrowRight', email);
    navigate(email, 'ArrowLeft', telegram);
    navigate(telegram, 'Home', email);
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it('shows the Telegram tab only when the server reports the integration enabled', async () => {
    apiMocks.get.mockResolvedValue({ data: { telegram_login_enabled: true } });

    render(<LoginPage />);

    expect(await screen.findByRole('tab', { name: 'Telegram' })).toBeInTheDocument();
  });
});
