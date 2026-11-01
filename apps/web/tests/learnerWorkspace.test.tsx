import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const translate = vi.hoisted(() => (key: string) => key);
vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: translate }) }));

import { LearnerEvidenceConfirmation } from '@/features/learner-workspace/LearnerEvidenceConfirmation';
import { getLearnerWorkspaceCopy, isFocusedLearnerRoute } from '@/features/learner-workspace/copy';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

const event = {
  id: 'event-1', procedure_type: 'knowledge_check', confirmation_status: 'pending',
  occurred_at: '2026-11-01T10:00:00Z', confirmation_statement: 'The exact saved test result',
};
const props = { eventId: event.id, activityKind: 'quiz' as const, activityTitle: 'Knowledge check' };

describe('learner workspace evidence boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useLanguageStore.setState({ lang: 'en' });
    useAuthStore.setState({ accessToken: 'learner-token', user: { user_id: 'learner-1', role: 'student', email: 'learner@example.com' } as never });
    vi.stubGlobal('fetch', vi.fn());
    apiMock.get.mockResolvedValue({ data: event });
    apiMock.post.mockResolvedValue({ data: { challenge_id: 'challenge-1' } });
  });

  it.each(['ru', 'kk', 'en'] as const)('preserves not_required without OTP or fabricated confirmation in %s', async (lang) => {
    useLanguageStore.setState({ lang });
    apiMock.get.mockResolvedValue({ data: { ...event, confirmation_status: 'not_required' } });
    render(<LearnerEvidenceConfirmation {...props} />);
    expect(await screen.findByRole('heading', { name: getLearnerWorkspaceCopy(lang).confirmationNotRequired })).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledExactlyOnceWith('/v1/training-evidence/events/mine/event-1');
    expect(fetch).not.toHaveBeenCalled();
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(screen.queryByText('evidenceConfirmation.status.pending')).not.toBeInTheDocument();
    expect(screen.queryByText('evidenceConfirmation.subtitle')).not.toBeInTheDocument();
  });

  it('mounts the real panel for a scoped pending event and retains purpose-bound OTP commands', async () => {
    render(<LearnerEvidenceConfirmation {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: 'evidenceConfirmation.requestCode' }));
    expect(apiMock.post).toHaveBeenCalledWith('/v1/training-evidence/step-up/events/event-1/request', {});
    const code = await screen.findByLabelText('evidenceConfirmation.codeLabel');
    expect(screen.getByRole('button', { name: 'evidenceConfirmation.confirm' })).toBeDisabled();
    fireEvent.change(code, { target: { value: '123456' } });
    apiMock.get.mockResolvedValue({ data: { ...event, confirmation_status: 'confirmed' } });
    fireEvent.click(screen.getByRole('button', { name: 'evidenceConfirmation.confirm' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('evidenceConfirmation.status.confirmed'));
    expect(apiMock.post).toHaveBeenCalledWith('/v1/training-evidence/step-up/events/event-1/verify', { challenge_id: 'challenge-1', code: '123456' });
  });

  it.each([{ ...event, id: 'foreign-event' }, { ...event, procedure_type: 'training' }])('does not mount OTP for mismatched event scope', async (payload) => {
    apiMock.get.mockResolvedValue({ data: payload });
    render(<LearnerEvidenceConfirmation {...props} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('evidenceConfirmation.errors.load');
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('retries unavailable evidence without assuming that confirmation is absent', async () => {
    apiMock.get.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ data: { ...event, confirmation_status: 'not_required' } });
    render(<LearnerEvidenceConfirmation {...props} />);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    await screen.findByRole('heading', { name: 'Confirmation not required' });
  });

  it('ignores a delayed old-session event after the actor changes', async () => {
    let resolve!: (value: { data: typeof event }) => void;
    apiMock.get.mockReturnValueOnce(new Promise((done) => { resolve = done; })).mockResolvedValue({ data: { ...event, confirmation_status: 'not_required' } });
    render(<LearnerEvidenceConfirmation {...props} />);
    act(() => useAuthStore.setState({ accessToken: 'new-learner-token', user: { user_id: 'learner-2', role: 'student' } as never }));
    await screen.findByRole('heading', { name: 'Confirmation not required' });
    await act(async () => { resolve({ data: event }); });
    expect(screen.queryByText('evidenceConfirmation.status.pending')).not.toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('retains signed-copy controls and PDF when course confirmation is not required', async () => {
    apiMock.get.mockImplementation(async (url: string) => ({ data: url.endsWith('/signed-scans')
      ? { status: 'awaiting_return', scans: [] }
      : { ...event, procedure_type: 'training', confirmation_status: 'not_required' } }));
    render(<LearnerEvidenceConfirmation {...props} activityKind="course" />);
    await screen.findByRole('heading', { name: 'Confirmation not required' });
    expect(screen.getByText('evidenceConfirmation.signedCopy')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'evidenceConfirmation.downloadPdf' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'evidenceConfirmation.requestCode' })).not.toBeInTheDocument();
    expect(apiMock.get.mock.calls.filter(([url]) => url === '/v1/training-evidence/events/mine/event-1')).toHaveLength(1);
  });

  it('preserves the OTP challenge and code across same-actor token refresh', async () => {
    render(<LearnerEvidenceConfirmation {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: 'evidenceConfirmation.requestCode' }));
    fireEvent.change(await screen.findByLabelText('evidenceConfirmation.codeLabel'), { target: { value: '123456' } });
    act(() => useAuthStore.setState({ accessToken: 'refreshed-token' }));
    expect(screen.getByLabelText('evidenceConfirmation.codeLabel')).toHaveValue('123456');
    expect(apiMock.get).toHaveBeenCalledTimes(1);
  });

  it('shows PDF download failures when OTP is not required', async () => {
    apiMock.get.mockImplementation((url: string) => url.endsWith('/export')
      ? Promise.reject(new Error('export unavailable'))
      : Promise.resolve({ data: { ...event, confirmation_status: 'not_required' } }));
    render(<LearnerEvidenceConfirmation {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: 'evidenceConfirmation.downloadPdf' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('evidenceConfirmation.downloadFailed');
    expect(screen.queryByRole('button', { name: 'evidenceConfirmation.requestCode' })).not.toBeInTheDocument();
  });

  it.each(['actor', 'event'] as const)('rejects a deferred old PDF after %s changes', async (change) => {
    let resolve!: (value: { data: Blob }) => void;
    apiMock.get.mockImplementation((url: string) => url.endsWith('/export')
      ? new Promise((done) => { resolve = done; })
      : Promise.resolve({ data: { ...event, id: url.split('/').at(-1) } }));
    const createUrl = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const view = render(<LearnerEvidenceConfirmation {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: 'evidenceConfirmation.downloadPdf' }));
    if (change === 'actor') act(() => useAuthStore.setState({ user: { user_id: 'learner-2', role: 'student' } as never }));
    else view.rerender(<LearnerEvidenceConfirmation {...props} eventId="event-2" />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(3));
    await act(async () => resolve({ data: new Blob(['%PDF-1.7'], { type: 'application/pdf' }) }));
    expect(createUrl).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
  });

  it('does not expose learner confirmation commands in privileged preview', () => {
    useAuthStore.setState({ user: { user_id: 'methodologist-1', role: 'methodologist' } as never });
    render(<LearnerEvidenceConfirmation {...props} />);
    expect(fetch).not.toHaveBeenCalled();
    expect(apiMock.post).not.toHaveBeenCalled();
  });
});

describe('focused learner route contract', () => {
  it('focuses only student course and quiz readers, not authoring, preview or other roles', () => {
    expect(isFocusedLearnerRoute('student', '/courses/course-1')).toBe(true);
    expect(isFocusedLearnerRoute('student', '/courses/quiz/quiz-1')).toBe(true);
    for (const path of ['/courses', '/my-courses', '/courses/course-1/edit', '/courses/quiz/quiz-1/preview']) expect(isFocusedLearnerRoute('student', path)).toBe(false);
    for (const role of ['methodologist', 'admin', 'superadmin', undefined]) expect(isFocusedLearnerRoute(role, '/courses/course-1')).toBe(false);
  });
});
