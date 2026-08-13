import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const authUser = vi.hoisted(() => ({ email: 'learner@example.kz' as string | null }));
const tMock = vi.hoisted(() => (
  key: string,
  params?: Record<string, string | number>,
) => key.replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? `{${name}}`)));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: tMock }),
}));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { user: { email: string | null } }) => unknown) => selector({ user: authUser }),
}));

import { EvidenceConfirmationPanel } from '@/features/training-evidence/EvidenceConfirmationPanel';

const pendingEvent = {
  id: 'event-1',
  enrollment_id: 'enrollment-1',
  content_release_id: 'release-1',
  procedure_type: 'training',
  record_type: 'original',
  related_event_id: null,
  occurred_at: '2026-07-31T10:00:00Z',
  created_at: '2026-07-31T10:00:00Z',
  confirmation_status: 'pending',
  release_version: 1,
  release_sha256: 'a'.repeat(64),
  confirmation_object_version: 'release:1',
  confirmation_statement: 'Я подтверждаю выполнение курса.',
};

describe('EvidenceConfirmationPanel', () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.post.mockReset();
    apiMock.get.mockReturnValue({ data: pendingEvent });
    apiMock.post.mockReturnValue({ data: { challenge_id: 'challenge-123456789', expires_in: 600 } });
    authUser.email = 'learner@example.kz';
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:evidence'),
      revokeObjectURL: vi.fn(),
    });
  });

  it('loads own event, requests OTP with an empty body, and verifies only challenge id and code', async () => {
    render(
      <EvidenceConfirmationPanel
        eventId="event-1"
        activityTitle="Политика безопасности"
        activityKind="course"
        continueHref="/courses"
      />,
    );

    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    await waitFor(() => expect(document.body.textContent).toContain('evidenceConfirmation.title'));
    expect(apiMock.get).toHaveBeenCalledWith('/v1/training-evidence/events/mine/event-1');

    const requestButton = await waitFor(() => screen.getByRole('button', { name: 'evidenceConfirmation.requestCode' }));
    fireEvent.click(requestButton);
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/training-evidence/step-up/events/event-1/request',
      {},
    ));

    const codeInput = await screen.findByLabelText('evidenceConfirmation.codeLabel');
    fireEvent.change(codeInput, { target: { value: '123456' } });
    const confirmButton = await waitFor(() => screen.getByRole('button', { name: 'evidenceConfirmation.confirm' }));
    fireEvent.click(confirmButton);
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/training-evidence/step-up/events/event-1/verify',
      { challenge_id: 'challenge-123456789', code: '123456' },
    ));
    expect(apiMock.post.mock.calls[1][1]).not.toHaveProperty('action_text');
    expect(apiMock.post.mock.calls[1][1]).not.toHaveProperty('object_version');
  });

  it('offers the learner their own printable evidence PDF before email confirmation', async () => {
    render(
      <EvidenceConfirmationPanel
        eventId="event-1"
        activityTitle="Политика безопасности"
        activityKind="course"
      />,
    );

    apiMock.get.mockImplementation((path: string) => (
      path.endsWith('/export')
        ? { data: new Blob(['pdf'], { type: 'application/pdf' }) }
        : { data: pendingEvent }
    ));

    fireEvent.click(await screen.findByRole('button', { name: 'Скачать подтверждение прохождения' }));

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(
      '/v1/training-evidence/events/mine/event-1/export',
      { params: { format: 'pdf' }, responseType: 'blob' },
    ));
  });

  it('does not offer email confirmation when the learner has no email', async () => {
    authUser.email = null;
    render(
      <EvidenceConfirmationPanel
        eventId="event-1"
        activityTitle="Политика безопасности"
        activityKind="course"
      />,
    );

    expect(await screen.findByText(/Электронное подтверждение недоступно/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'evidenceConfirmation.requestCode' })).not.toBeInTheDocument();
  });
});
