import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { post } }));

import RegisterPage from '@/app/register/page';

describe('legacy Telegram registration legal acknowledgements', () => {
  beforeEach(() => post.mockReset());

  it('requires separate acknowledgements and sends their audit fields', async () => {
    post.mockResolvedValue({ data: { tenant_slug: 'acme', tenant_name: 'Acme' } });
    render(<RegisterPage />);

    const button = screen.getByRole('button', { name: 'Создать организацию' });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Название компании/i), { target: { value: 'Acme' } });
    fireEvent.change(screen.getByLabelText(/^Имя/), { target: { value: 'Алия' } });
    fireEvent.change(screen.getByLabelText(/^Фамилия/), { target: { value: 'Тестова' } });
    fireEvent.change(screen.getByLabelText(/Telegram ID/i), { target: { value: '123456' } });
    screen.getAllByRole('checkbox').forEach((checkbox) => fireEvent.click(checkbox));
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith('/v1/auth/register-by-telegram', expect.objectContaining({
      privacy_consent_version: '2026-08-10',
      privacy_consent_locale: 'ru',
      privacy_consent_surface: 'telegram_registration',
      terms_version: '2026-08-10',
    }));
    const payload = post.mock.calls[0]?.[1] as Record<string, unknown>;
    expect(payload).not.toHaveProperty('privacy_consent_at');
    expect(payload).not.toHaveProperty('terms_accepted_at');
  });
});
