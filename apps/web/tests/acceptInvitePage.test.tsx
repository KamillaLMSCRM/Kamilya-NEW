import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));
const loginMock = vi.hoisted(() => vi.fn());
const replaceMock = vi.hoisted(() => vi.fn());

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  useSearchParams: () => new URLSearchParams('token=invite-token'),
}));
vi.mock('@/store/authStore', () => ({
  useAuthStore: Object.assign(
    () => ({
      login: loginMock,
      accessToken: null,
    }),
    {
      getState: () => ({
        user: null,
      }),
    },
  ),
}));

import AcceptInvitePage from '@/app/accept-invite/page';

describe('employee invitation activation', () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.post.mockReset();
    loginMock.mockReset();
    replaceMock.mockReset();
    apiMock.get.mockResolvedValue({
      data: {
        masked_email: 'e*******@example.kz',
        tenant_name: 'ТОО Тест',
        role: 'student',
        first_name: 'Айжан',
        last_name: 'Ахметова',
        position_name: 'Кассир',
        course_titles: ['Вводный курс'],
        expires_at: '2026-08-01T12:00:00Z',
        valid: true,
        reason_if_invalid: null,
      },
    });
  });

  it('shows HR-managed identity without editable profile or password fields', async () => {
    render(<AcceptInvitePage />);

    expect(await screen.findByText('Айжан Ахметова')).toBeInTheDocument();
    expect(screen.getByText('Кассир')).toBeInTheDocument();
    expect(screen.getByText('e*******@example.kz')).toBeInTheDocument();
    expect(screen.getByText('Вводный курс')).toBeInTheDocument();
    expect(screen.queryByLabelText('Имя')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Фамилия')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Табельный номер/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Пароль/i)).not.toBeInTheDocument();
  });

  it('requests OTP, verifies it and opens the assigned course', async () => {
    apiMock.post
      .mockResolvedValueOnce({
        data: { ok: true, expires_in: 300, retry_after: 60 },
      })
      .mockResolvedValueOnce({
        data: {
          access_token: 'access-token',
          user: { id: 'user-1', role: 'student', roles: ['student'] },
          role: 'student',
          next_url: '/courses/course-1',
        },
      });
    render(<AcceptInvitePage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Получить код' }));
    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledWith(
        '/v1/invitations/invite-token/request-code',
      );
    });

    fireEvent.change(screen.getByLabelText('Код из письма'), {
      target: { value: '123456' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Подтвердить и начать обучение' }),
    );

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenLastCalledWith(
        '/v1/invitations/invite-token/accept',
        { code: '123456' },
      );
    });
    expect(loginMock).toHaveBeenCalledWith(
      'access-token',
      expect.objectContaining({ id: 'user-1' }),
    );
    expect(replaceMock).toHaveBeenCalledWith('/courses/course-1');
  });
});
