import { act, fireEvent, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ token: 'test-token', lang: 'en', user: { user_id: 'user-1', tenant_id: 'tenant-1', role: 'methodologist' } }));
const translate = (key: string) => ({
  'aiAssistant.chatPlaceholder': 'Ask AI', 'aiGeneration.chat.send': 'Send',
  'aiAssistant.intro': 'Ask about this course', 'aiAssistant.applyLesson': 'Apply',
  'aiAssistant.errorReply': 'Could not respond', 'aiAssistant.lessonUpdated': 'Updated',
}[key] ?? key);
vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: (value: unknown) => unknown) => selector({ accessToken: state.token, user: state.user }) }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: state.lang, t: translate }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import { toast } from '@/components/ui/Toast';
import { AIChatPanel } from '@/components/ai/AIChatPanel';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const response = (data: unknown) => ({ ok: true, json: async () => data }) as Response;
function send(text = 'Explain this lesson') {
  fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
}

describe('AI chat context lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks(); state.token = 'test-token'; state.lang = 'en';
    state.user = { user_id: 'user-1', tenant_id: 'tenant-1', role: 'methodologist' };
  });
  afterEach(() => vi.unstubAllGlobals());

  it('clears the conversation and unsent input when the course changes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ reply: 'Course one answer' })));
    const { rerender } = render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" />);
    send(); await screen.findByText('Course one answer');
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Unsent for course one' } });
    rerender(<AIChatPanel open onClose={vi.fn()} courseId="course-2" />);
    expect(screen.queryByText('Course one answer')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toHaveValue('');
  });

  it.each(['course', 'lesson', 'module', 'reopen', 'token', 'user', 'tenant', 'role', 'language'])('rejects a late answer after a %s change, even if the transport ignores abort', async (change) => {
    const pending = deferred<Response>();
    const fetchMock = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(response({ reply: 'Current answer' }));
    vi.stubGlobal('fetch', fetchMock);
    const onClose = vi.fn();
    const original = { open: true, onClose, courseId: 'course-1', focusLessonId: change === 'module' ? undefined : 'lesson-1', focusModuleId: change === 'module' ? 'module-1' : undefined };
    const { rerender } = render(<AIChatPanel {...original} />);
    send();
    if (change === 'token') state.token = 'new-token';
    if (change === 'language') state.lang = 'kk';
    if (change === 'user') state.user = { ...state.user, user_id: 'user-2' };
    if (change === 'tenant') state.user = { ...state.user, tenant_id: 'tenant-2' };
    if (change === 'role') state.user = { ...state.user, role: 'admin' };
    if (change === 'reopen') rerender(<AIChatPanel {...original} open={false} />);
    rerender(<AIChatPanel {...original} courseId={change === 'course' ? 'course-2' : 'course-1'} focusLessonId={change === 'lesson' ? 'lesson-2' : original.focusLessonId} focusModuleId={change === 'module' ? 'module-2' : undefined} />);
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeEnabled();
    send('Current question');
    await screen.findByText('Current answer');
    await act(async () => pending.resolve(response({ reply: 'Wrong old answer', apply_lesson_id: 'old-lesson', apply_lesson_content: 'Wrong patch' })));
    expect(screen.queryByText('Wrong old answer')).not.toBeInTheDocument();
    expect(screen.queryByText('Wrong patch')).not.toBeInTheDocument();
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
  });

  it('does not display an old failure in a reopened chat', async () => {
    const pending = deferred<Response>(); vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending.promise));
    const props = { courseId: 'course-1', onClose: vi.fn() };
    const { rerender } = render(<AIChatPanel {...props} open />);
    send(); rerender(<AIChatPanel {...props} open={false} />); rerender(<AIChatPanel {...props} open />);
    await act(async () => pending.reject(new Error('late network failure')));
    expect(screen.queryByText('Could not respond')).not.toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('does not let an old finally unlock a new pending request', async () => {
    const old = deferred<Response>(); const current = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise));
    const props = { onClose: vi.fn(), open: true };
    const { rerender } = render(<AIChatPanel {...props} courseId="course-1" />);
    send(); rerender(<AIChatPanel {...props} courseId="course-2" />); send('Current question');
    await act(async () => old.resolve(response({ reply: 'Old' })));
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeDisabled();
    await act(async () => current.resolve(response({ reply: 'Current' })));
    expect(screen.getByRole('textbox', { name: 'Ask AI' })).toBeEnabled();
  });

  it('sends one PATCH while an explicit apply is pending', async () => {
    const patch = deferred<Response>();
    const fetchMock = vi.fn().mockResolvedValueOnce(response({ reply: 'Proposal', apply_lesson_id: 'lesson-1', apply_lesson_content: 'Proposed lesson' })).mockReturnValue(patch.promise);
    vi.stubGlobal('fetch', fetchMock);
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" />);
    send(); const apply = await screen.findByRole('button', { name: 'Apply' });
    fireEvent.click(apply); fireEvent.click(apply);
    expect(fetchMock.mock.calls.filter(([, request]) => request.method === 'PATCH')).toHaveLength(1);
    expect(apply).toBeDisabled();
    await act(async () => patch.resolve(response({})));
  });

  it('does not notify the new editor after an old apply finishes', async () => {
    const patch = deferred<Response>(); const applied = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ reply: 'Proposal', apply_lesson_id: 'lesson-1', apply_lesson_content: 'Proposed lesson' })).mockReturnValue(patch.promise));
    const props = { open: true, onClose: vi.fn(), onLessonApplied: applied };
    const { rerender } = render(<AIChatPanel {...props} courseId="course-1" />);
    send(); fireEvent.click(await screen.findByRole('button', { name: 'Apply' }));
    rerender(<AIChatPanel {...props} courseId="course-2" />);
    await act(async () => patch.resolve(response({})));
    expect(applied).not.toHaveBeenCalled(); expect(toast.success).not.toHaveBeenCalled();
  });

  it('aborts the client request on unmount without claiming server rollback', () => {
    const pending = deferred<Response>(); const fetchMock = vi.fn().mockReturnValue(pending.promise);
    vi.stubGlobal('fetch', fetchMock);
    const { unmount } = render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" />);
    send(); unmount();
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it('remains usable after StrictMode setup/cleanup/setup', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ reply: 'Strict answer' }));
    vi.stubGlobal('fetch', fetchMock);
    render(<StrictMode><AIChatPanel open onClose={vi.fn()} courseId="course-1" /></StrictMode>);
    send(); await screen.findByText('Strict answer');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false);
  });

  it('checks context again after asynchronous response decoding', async () => {
    const decoded = deferred<unknown>();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => decoded.promise });
    vi.stubGlobal('fetch', fetchMock);
    const props = { open: true, onClose: vi.fn() };
    const { rerender } = render(<AIChatPanel {...props} courseId="course-1" />);
    await act(async () => send());
    rerender(<AIChatPanel {...props} courseId="course-2" />);
    await act(async () => decoded.resolve({ reply: 'Old decoded answer' }));
    expect(screen.queryByText('Old decoded answer')).not.toBeInTheDocument();
  });
});
