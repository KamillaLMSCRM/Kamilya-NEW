import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const state = vi.hoisted(() => ({ user: { user_id: 'u1', tenant_id: 't1', role: 'methodologist' }, lang: 'en' }));
const t = (key: string) => ({
  'aiAssistant.intro': 'Ask about this course', 'aiAssistant.chatPlaceholder': 'Ask AI',
  'aiAssistant.lessonPlaceholder': 'Ask AI to rewrite this lesson', 'aiGeneration.chat.send': 'Send',
  'aiAssistant.errorToast': 'Chat error', 'aiAssistant.dialogLabel': 'Assistant',
}[key] ?? key);

vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ accessToken: 'token', user: state.user }) }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: state.lang, t }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { AIChatPanel } from '@/components/ai/AIChatPanel';

const response = (body: unknown, ok = true) => ({ ok, json: async () => body }) as Response;
const history = (exchanges: unknown[], extra: Record<string, unknown> = {}) => response({ exchanges, has_more: false, next_before: null, pending_request_id: null, ...extra });

describe('durable selected-lesson dialogue', () => {
  beforeEach(() => { fetchMock.mockReset(); state.user = { user_id: 'u1', tenant_id: 't1', role: 'methodologist' }; state.lang = 'en'; vi.stubGlobal('fetch', fetchMock); vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test'); });
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it('hydrates archived exchanges as passive text and sends a durable follow-up without client history', async () => {
    fetchMock.mockResolvedValueOnce(history([{ id: 'x1', message: 'Earlier question', response: { reply: 'Earlier answer', apply_lesson_id: 'lesson-1', apply_lesson_content: 'Archived proposal' }, created_at: '2026-10-14T00:00:00Z' }]))
      .mockResolvedValueOnce(response({ reply: 'Fresh answer' }));
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" focusLessonId="lesson-1" />);
    await screen.findByText('Archived proposal', { exact: false });
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Follow up' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('Fresh answer');
    const request = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(request.durable_request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(request.history).toBeUndefined();
    expect(screen.queryByRole('button', { name: /apply/i })).not.toBeInTheDocument();
  });

  it('loads an earlier page with the server cursor', async () => {
    fetchMock.mockResolvedValueOnce(history([], { has_more: true, next_before: 'cursor-1' })).mockResolvedValueOnce(history([{ id: 'old', message: 'Old question', response: { reply: 'Old answer' }, created_at: '2026-10-13T00:00:00Z' }]));
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" focusLessonId="lesson-1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Load earlier messages' }));
    await screen.findByText('Old answer');
    expect(fetchMock.mock.calls[1][0]).toContain('before=cursor-1');
  });

  it('blocks sending on history failure until an explicit reload succeeds', async () => {
    fetchMock.mockResolvedValueOnce(response({}, false)).mockResolvedValueOnce(history([]));
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" focusLessonId="lesson-1" />);
    const reload = await screen.findByRole('button', { name: 'Reload history' });
    const input = screen.getByRole('textbox', { name: 'Ask AI' });
    fireEvent.change(input, { target: { value: 'Blocked question' } });
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    fireEvent.click(reload);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled());
  });

  it('offers pending recovery and never resends the unknown request', async () => {
    fetchMock.mockResolvedValueOnce(history([], { pending_request_id: 'pending-key' }))
      .mockResolvedValueOnce(history([{ id: 'done', message: 'Prior question', response: { reply: 'Now saved' }, created_at: '2026-10-14T00:00:00Z' }]));
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" focusLessonId="lesson-1" />);
    const reload = await screen.findByRole('button', { name: 'Reload history' });
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeDisabled();
    fireEvent.click(reload);
    await screen.findByText('Now saved');
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeEnabled();
    expect(fetchMock.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  });

  it('reconciles a lost POST response once as passive archive without duplicate messages or actions', async () => {
    const review = vi.fn();
    fetchMock.mockResolvedValueOnce(history([])).mockRejectedValueOnce(new Error('lost response'))
      .mockResolvedValueOnce(history([{ id: 'done', message: 'My question', response: { reply: 'Saved answer', history_eligible: true, apply_lesson_id: 'lesson-1', apply_lesson_content: 'Saved proposal' }, created_at: '2026-10-14T00:00:00Z' }]));
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" focusLessonId="lesson-1" onReviewLessonSuggestion={review} />);
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeEnabled());
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'My question' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Reload history' }));
    await screen.findByText('Saved answer', { exact: false });
    expect(screen.getAllByText('My question')).toHaveLength(1);
    expect(screen.queryByText(/outcome is unknown/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /sources|apply|correction/i })).not.toBeInTheDocument();
    expect(review).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1);
  });

  it.each([{}, { exchanges: [], has_more: false }, { exchanges: [null], has_more: false, next_before: null, pending_request_id: null }])('fails closed for malformed history %j', async (malformed) => {
    fetchMock.mockResolvedValue(response(malformed));
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" focusLessonId="lesson-1" />);
    await screen.findByRole('button', { name: 'Reload history' });
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeDisabled();
  });

  it.each(['lesson', 'actor', 'tenant', 'language'])('discards an abort-resistant old history result after %s change', async (change) => {
    let resolveOld!: (value: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(history([{ id: 'new', message: 'Current question', response: { reply: 'Current saved answer' }, created_at: '2026-10-14T00:00:00Z' }]));
    const props = { open: true, onClose: vi.fn(), courseId: 'course-1', focusLessonId: 'lesson-1' };
    const view = render(<AIChatPanel {...props} />);
    if (change === 'actor') state.user = { ...state.user, user_id: 'u2' };
    if (change === 'tenant') state.user = { ...state.user, tenant_id: 't2' };
    if (change === 'language') state.lang = 'ru';
    view.rerender(<AIChatPanel {...props} focusLessonId={change === 'lesson' ? 'lesson-2' : 'lesson-1'} />);
    await screen.findByText('Current saved answer');
    await act(async () => resolveOld(history([{ id: 'old', message: 'Old question', response: { reply: 'Wrong old answer' }, created_at: '2026-10-13T00:00:00Z' }])));
    expect(screen.queryByText('Wrong old answer')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
    expect(fetchMock.mock.calls).toHaveLength(2);
  });

  it('restores conversation after complete unmount/remount using GET alone', async () => {
    const saved = [{ id: 'saved', message: 'Previous question', response: { reply: 'Previous answer' }, created_at: '2026-10-14T00:00:00Z' }];
    fetchMock.mockResolvedValue(history(saved));
    const props = { open: true, onClose: vi.fn(), courseId: 'course-1', focusLessonId: 'lesson-1' };
    const first = render(<AIChatPanel {...props} />);
    await screen.findByText('Previous answer');
    first.unmount();
    render(<AIChatPanel {...props} />);
    await screen.findByText('Previous answer');
    expect(fetchMock.mock.calls).toHaveLength(2);
    expect(fetchMock.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  });

  it('explicitly reports interruption while allowing a consciously entered new question', async () => {
    fetchMock.mockResolvedValueOnce(history([], { interrupted_request_id: 'expired' })).mockResolvedValueOnce(response({ reply: 'New answer' }));
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" focusLessonId="lesson-1" />);
    await screen.findByText(/previous request was interrupted/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeEnabled();
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Conscious new question' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('New answer');
    expect(screen.queryByText(/previous request was interrupted/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init.method === 'POST')).toHaveLength(1);
  });
});
