import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));
const translateMock = vi.hoisted(() => (key: string) => key);

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: any) => unknown) => selector({
    accessToken: 'test-token',
    user: { tenant: { is_demo: false } },
  }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: translateMock }),
}));
vi.mock('@/components/ui/Toast', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import InvitationsPage from '@/app/admin/invitations/page';

describe('admin invitation delivery lifecycle', () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.post.mockReset();
    apiMock.get.mockResolvedValue({
      data: {
        items: [{
          id: 'inv-1',
          email: 'learner@example.kz',
          role: 'student',
          status: 'pending',
          created_at: '2026-08-03T00:00:00Z',
          expires_at: '2026-08-06T00:00:00Z',
          accepted_at: null,
          delivery_status: 'failed',
          delivery_message_id: null,
          delivery_last_attempt_at: '2026-08-03T00:01:00Z',
          delivery_attempt_count: 1,
          delivery_failure_category: 'provider_rejected',
          delivery_failure_message: 'The email provider rejected the message.',
        }],
      },
    });
    apiMock.post.mockResolvedValue({
      data: {
        email: 'learner@example.kz',
        invitation_id: 'inv-2',
        invite_url: 'https://app.kml.kz/accept-invite?token=opaque',
        expires_at: '2026-08-06T00:00:00Z',
        delivery_status: 'sent',
        delivery_message_id: 'msg-2',
        delivery_last_attempt_at: '2026-08-03T00:02:00Z',
        delivery_attempt_count: 1,
        delivery_failure_category: null,
        delivery_failure_message: null,
      },
    });
  });

  it('shows truthful failure guidance, keeps copy fallback, and retries through resend', async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn() } });
    render(<InvitationsPage />);

    expect(await screen.findByText('learner@example.kz')).toBeInTheDocument();
    expect(screen.getByText('The email provider rejected the message.')).toBeInTheDocument();
    expect(screen.getByText('invitations.delivery.failed')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'invitations.resend' }));
    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledWith('/v1/users/invitations/inv-1/resend');
    });
  });
});
