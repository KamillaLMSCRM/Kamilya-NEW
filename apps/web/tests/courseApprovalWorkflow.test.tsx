import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const configureMock = vi.hoisted(() => vi.fn());
const getPolicyMock = vi.hoisted(() => vi.fn());
const decisionMock = vi.hoisted(() => vi.fn());
const progressMock = vi.hoisted(() => vi.fn());
const testMock = vi.hoisted(() => vi.fn());
const getRequestMock = vi.hoisted(() => vi.fn());
const getScopedRequestMock = vi.hoisted(() => vi.fn());
const startAttemptMock = vi.hoisted(() => vi.fn());
const replaceMock = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useParams: () => ({ requestId: 'request' }), useRouter: () => ({ replace: replaceMock }) }));
vi.mock('@/lib/courseApproval', async () => {
  const actual = await vi.importActual<typeof import('@/lib/courseApproval')>('@/lib/courseApproval');
  return { ...actual, configureApprovalPolicy: configureMock, getApprovalPolicy: getPolicyMock, submitReviewDecision: decisionMock, saveReviewProgress: progressMock, submitReviewTest: testMock, getApprovalRequest: getRequestMock, getScopedReviewRequest: getScopedRequestMock, startReviewAttempt: startAttemptMock };
});
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ApprovalPolicyCard } from '@/components/course-approval/ApprovalPolicyCard';
import { ReviewerDecisionPanel } from '@/components/course-approval/ReviewerDecisionPanel';
import { ReviewCoursePlayer } from '@/components/course-approval/ReviewCoursePlayer';
import { ReviewRequestScreen } from '@/components/course-approval/ReviewRequestScreen';
import ScopedReviewRequestPage from '@/app/course-review-access/review/requests/[requestId]/page';
import { useAuthStore } from '@/store/authStore';

const snapshot = { schema_version: 1, release_version: 3, course: { id: 'course', title: 'Курс' }, modules: [{ id: 'module', title: 'Модуль', order_index: 0, lessons: [{ id: 'lesson', title: 'Урок', content_type: 'text', content: 'Текст', order_index: 0, quizzes: [{ id: 'quiz', title: 'Тест', pass_score: 80, questions: [{ id: 'question', text: 'Вопрос', type: 'single_choice', points: 1, order_index: 0, choices: [{ id: 'choice-1', text: 'Правильный текст', order_index: 0 }] }] }] }] }] };
const resumeSnapshot = { ...snapshot, release_version: 4, modules: [{ ...snapshot.modules[0], lessons: [snapshot.modules[0].lessons[0], { id: 'lesson-2', title: 'Второй урок', content_type: 'text', content: '# Второй урок\n\nТекст второго урока', order_index: 1, quizzes: [] }] }] };

describe('course approval workflow UI', () => {
  beforeEach(() => { sessionStorage.clear(); });
  beforeEach(() => { configureMock.mockReset().mockResolvedValue({ requires_approval: true, review_enabled: true }); getPolicyMock.mockReset().mockResolvedValue({ requires_approval: false, review_enabled: true }); decisionMock.mockReset().mockResolvedValue({}); progressMock.mockReset().mockResolvedValue({}); testMock.mockReset().mockResolvedValue({ diagnostics: { answered: 1, total: 1, correct: 1, score_percent: 100, complete: true } }); getRequestMock.mockReset(); getScopedRequestMock.mockReset(); startAttemptMock.mockReset(); });

  it('never enters the ordinary reviewer session when a public review capability is absent', async () => {
    sessionStorage.removeItem('course_review_token');
    render(<ScopedReviewRequestPage />);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(getRequestMock).not.toHaveBeenCalled();
    expect(getScopedRequestMock).not.toHaveBeenCalled();
    expect(startAttemptMock).not.toHaveBeenCalled();
  });

  it('persists the opt-in policy and gives a clear immutable-snapshot hint', async () => {
    // Starting the request is not the same as rendering its loaded policy.
    getPolicyMock.mockImplementationOnce(() => new Promise((resolve) => {
      setTimeout(() => resolve({ requires_approval: false, review_enabled: true }), 50);
    }));
    render(<ApprovalPolicyCard courseId="course" />);
    await waitFor(() => expect(getPolicyMock).toHaveBeenCalledWith('course'));
    fireEvent.click(await screen.findByRole('checkbox'));
    await waitFor(() => expect(configureMock).toHaveBeenCalledWith('course', true));
    expect(screen.getByText(/неизменяемый снимок/i)).toBeInTheDocument();
  });

  it('keeps writes disabled on a failed policy read instead of assuming an unchecked policy', async () => {
    getPolicyMock.mockRejectedValueOnce(new Error('offline'));
    render(<ApprovalPolicyCard courseId="course" />);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось открыть проверку');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('checkbox')).toBeInTheDocument();
    expect(configureMock).not.toHaveBeenCalled();
  });

  it('ignores a stale policy response after the course changes', async () => {
    let resolveFirst: (value: { requires_approval: boolean; review_enabled: boolean }) => void = () => undefined;
    getPolicyMock.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    getPolicyMock.mockResolvedValueOnce({ requires_approval: true, review_enabled: true });
    const view = render(<ApprovalPolicyCard courseId="course-a" />);
    view.rerender(<ApprovalPolicyCard courseId="course-b" />);
    await waitFor(() => expect(getPolicyMock).toHaveBeenLastCalledWith('course-b'));
    expect(await screen.findByRole('checkbox')).toBeChecked();
    resolveFirst({ requires_approval: false, review_enabled: true });
    await waitFor(() => expect(screen.getByRole('checkbox')).toBeChecked());
  });

  it('ignores a pending policy PATCH after switching courses', async () => {
    let resolvePatch: (value: { requires_approval: boolean; review_enabled: boolean }) => void = () => undefined;
    configureMock.mockImplementationOnce(() => new Promise((resolve) => { resolvePatch = resolve; }));
    const view = render(<ApprovalPolicyCard courseId="course-a" />);
    expect(await screen.findByRole('checkbox')).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(configureMock).toHaveBeenCalledWith('course-a', true));
    view.rerender(<ApprovalPolicyCard courseId="course-b" />);
    expect(await screen.findByRole('checkbox')).not.toBeChecked();
    resolvePatch({ requires_approval: true, review_enabled: true });
    await waitFor(() => expect(screen.getByRole('checkbox')).not.toBeChecked());
  });

  it('requires acknowledgement before an early approval and requires a return reason', async () => {
    render(<ReviewerDecisionPanel attemptId="attempt" activityState="in_progress" />);
    fireEvent.click(screen.getByRole('button', { name: 'Согласовать версию' }));
    expect(decisionMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Согласовать версию' }));
    expect(decisionMock).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить решение' }));
    await waitFor(() => expect(decisionMock).toHaveBeenCalledWith('attempt', 'approve', null, true, undefined));
  });

  it('renders the reviewer snapshot structurally without answer-key fields', () => {
    render(<ReviewCoursePlayer snapshot={snapshot} attemptId="attempt" onComplete={() => undefined} />);
    expect(screen.getByText('Правильный текст')).toBeInTheDocument();
    expect(screen.queryByText(/is_correct/i)).not.toBeInTheDocument();
    expect(screen.getByText('Режим проверки')).toBeInTheDocument();
  });

  it('freezes the trimmed return reason in the decision confirmation', async () => {
    render(<ReviewerDecisionPanel attemptId="attempt-return" snapshotLabel="snapshot-a" activityState="completed" />);
    expect(screen.getByRole('button', { name: 'Вернуть на доработку' })).toBeDisabled();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '  Уточните условие задачи  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Вернуть на доработку' }));
    expect(decisionMock).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toHaveTextContent('snapshot-a');
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить решение' }));
    await waitFor(() => expect(decisionMock).toHaveBeenCalledWith('attempt-return', 'return', 'Уточните условие задачи', false, undefined));
  });

  it('dismisses a prepared decision when the attempt or snapshot changes', () => {
    const view = render(<ReviewerDecisionPanel attemptId="attempt-a" snapshotLabel="sha-a" activityState="completed" />);
    fireEvent.click(screen.getByRole('button', { name: 'Согласовать версию' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    view.rerender(<ReviewerDecisionPanel attemptId="attempt-b" snapshotLabel="sha-b" activityState="completed" />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(decisionMock).not.toHaveBeenCalled();
  });

  it('blocks retrying a conflicting decision until the request is reloaded', async () => {
    decisionMock.mockRejectedValueOnce({ response: { status: 409 } });
    const reload = vi.fn();
    render(<ReviewerDecisionPanel attemptId="attempt" activityState="completed" onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Согласовать версию' }));
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить решение' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'Согласовать версию' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('rejects a delayed old-attempt decision callback', async () => {
    let resolve!: (value: object) => void;
    decisionMock.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const submitted = vi.fn();
    const view = render(<ReviewerDecisionPanel attemptId="attempt-a" activityState="completed" onSubmitted={submitted} />);
    fireEvent.click(screen.getByRole('button', { name: 'Согласовать версию' }));
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить решение' }));
    view.rerender(<ReviewerDecisionPanel attemptId="attempt-b" activityState="completed" onSubmitted={submitted} />);
    await act(async () => resolve({}));
    expect(submitted).not.toHaveBeenCalled();
  });

  it('does not restore a late old-request snapshot over a new request', async () => {
    let resolve!: (value: unknown) => void;
    getRequestMock.mockReturnValueOnce(new Promise((done) => { resolve = done; })).mockResolvedValue({ request_id: 'request-b', revision_id: 'rev-b', outcome: 'pending' });
    startAttemptMock.mockResolvedValueOnce({ attempt_id: 'attempt-a', snapshot_sha256: 'sha-a', activity_state: 'completed', snapshot })
      .mockResolvedValueOnce({ attempt_id: 'attempt-b', snapshot_sha256: 'sha-b', activity_state: 'completed', snapshot });
    const view = render(<ReviewRequestScreen requestId="request-a" />);
    view.rerender(<ReviewRequestScreen requestId="request-b" />);
    await screen.findByText('Снимок: sha-b');
    await act(async () => resolve({ request_id: 'request-a', revision_id: 'rev-a', outcome: 'pending' }));
    expect(screen.queryByText('Снимок: sha-a')).not.toBeInTheDocument();
    expect(screen.getByText('Снимок: sha-b')).toBeInTheDocument();
  });

  it('rejects an old ordinary-session review after its actor changes', async () => {
    const original = useAuthStore.getState();
    let resolve!: (value: unknown) => void;
    act(() => useAuthStore.setState({ accessToken: 'ordinary-a', user: { user_id: 'reviewer-a', tenant_id: 'tenant-a', role: 'methodologist' } as never }));
    getRequestMock.mockReturnValueOnce(new Promise((done) => { resolve = done; })).mockResolvedValue({ request_id: 'request', revision_id: 'rev-b', outcome: 'pending' });
    startAttemptMock.mockResolvedValueOnce({ attempt_id: 'attempt-a', snapshot_sha256: 'sha-a', activity_state: 'completed', snapshot })
      .mockResolvedValueOnce({ attempt_id: 'attempt-b', snapshot_sha256: 'sha-b', activity_state: 'completed', snapshot });
    const view = render(<ReviewRequestScreen requestId="request" />);
    act(() => useAuthStore.setState({ accessToken: 'ordinary-b', user: { user_id: 'reviewer-b', tenant_id: 'tenant-b', role: 'methodologist' } as never }));
    await screen.findByText('Снимок: sha-b');
    await act(async () => resolve({ request_id: 'request', revision_id: 'rev-a', outcome: 'pending' }));
    expect(screen.queryByText('Снимок: sha-a')).not.toBeInTheDocument();
    expect(screen.getByText('Снимок: sha-b')).toBeInTheDocument();
    view.unmount();
    act(() => useAuthStore.setState({ user: original.user, accessToken: original.accessToken }));
  });

  it('sends interactive quiz answers only through the review progress endpoint', async () => {
    render(<ReviewCoursePlayer snapshot={snapshot} attemptId="attempt" onComplete={() => undefined} />);
    fireEvent.click(screen.getByLabelText('Правильный текст'));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ответы' }));
    await waitFor(() => expect(testMock).toHaveBeenCalledWith('attempt', [{ question_id: 'question', selected_choice_ids: ['choice-1'] }], undefined));
    expect(screen.getByRole('status')).toHaveTextContent('100%');
  });

  it('submits cumulative answers across lesson quizzes with one course-wide result', async () => {
    const secondQuestion = { ...snapshot.modules[0].lessons[0].quizzes[0].questions[0], id: 'question-2', text: 'Второй вопрос', choices: [{ id: 'choice-2', text: 'Второй ответ', order_index: 0 }] };
    const multi = { ...resumeSnapshot, modules: [{ ...resumeSnapshot.modules[0], lessons: [snapshot.modules[0].lessons[0], { ...resumeSnapshot.modules[0].lessons[1], quizzes: [{ ...snapshot.modules[0].lessons[0].quizzes[0], id: 'quiz-2', title: 'Второй тест', questions: [secondQuestion] }] }] }] };
    testMock.mockResolvedValueOnce({ diagnostics: { answered: 1, total: 2, correct: 1, score_percent: 50, complete: false } });
    testMock.mockResolvedValueOnce({ diagnostics: { answered: 2, total: 2, correct: 2, score_percent: 100, complete: true } });
    const view = render(<ReviewCoursePlayer snapshot={multi} attemptId="attempt" answerStorageScope="tenant-a:reviewer-a" onComplete={() => undefined} />);
    expect(screen.getByRole('button', { name: 'Отправить ответы' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Правильный текст'));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ответы' }));
    await waitFor(() => expect(testMock).toHaveBeenCalledWith('attempt', [{ question_id: 'question', selected_choice_ids: ['choice-1'] }], undefined));
    expect(screen.getByRole('status')).toHaveTextContent('Результат по всему курсу: отвечено 1 из 2, 50%');
    view.unmount();
    render(<ReviewCoursePlayer snapshot={multi} attemptId="attempt" answerStorageScope="tenant-a:reviewer-a" onComplete={() => undefined} />);
    expect(screen.getByLabelText('Правильный текст')).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' }));
    await screen.findByText('Второй вопрос');
    expect(screen.getByRole('button', { name: 'Отправить ответы' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Второй ответ'));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ответы' }));
    await waitFor(() => expect(testMock).toHaveBeenLastCalledWith('attempt', [
      { question_id: 'question', selected_choice_ids: ['choice-1'] },
      { question_id: 'question-2', selected_choice_ids: ['choice-2'] },
    ], undefined));
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByRole('status')).toHaveTextContent('отвечено 2 из 2, 100%');
  });

  it('never restores review draft choices from another principal, attempt or snapshot', () => {
    const key = JSON.stringify(['kamilya-review-answers-v1', 'tenant-a:reviewer-a', 'attempt-a', 'sha-a']);
    sessionStorage.setItem(key, JSON.stringify({ question: 'choice-1', foreign: 'choice-evil' }));
    const view = render(<ReviewCoursePlayer snapshot={snapshot} snapshotIdentity="sha-a" attemptId="attempt-a" answerStorageScope="tenant-a:reviewer-a" onComplete={() => undefined} />);
    expect(screen.getByLabelText('Правильный текст')).toBeChecked();
    for (const [principal, attempt, sha] of [['tenant-b:reviewer-b', 'attempt-a', 'sha-a'], ['tenant-a:reviewer-a', 'attempt-b', 'sha-a'], ['tenant-a:reviewer-a', 'attempt-a', 'sha-b']]) {
      view.rerender(<ReviewCoursePlayer snapshot={snapshot} snapshotIdentity={sha} attemptId={attempt} answerStorageScope={principal} onComplete={() => undefined} />);
      expect(screen.getByLabelText('Правильный текст')).not.toBeChecked();
    }
    sessionStorage.setItem(key, JSON.stringify({ question: 'foreign-choice' }));
    view.rerender(<ReviewCoursePlayer snapshot={snapshot} snapshotIdentity="sha-a" attemptId="attempt-a" answerStorageScope="tenant-a:reviewer-a" onComplete={() => undefined} />);
    expect(screen.getByLabelText('Правильный текст')).not.toBeChecked();
  });

  it('does not consume a checkpoint sequence for quiz submission', async () => {
    testMock.mockResolvedValueOnce({ diagnostics: { answered: 1, total: 1, correct: 0, score_percent: 0, complete: false } });
    render(<ReviewCoursePlayer snapshot={resumeSnapshot} attemptId="attempt" initialNextSequence={7} onComplete={() => undefined} />);
    fireEvent.click(screen.getByLabelText('Правильный текст'));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ответы' }));
    await waitFor(() => expect(testMock).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' }));
    await waitFor(() => expect(progressMock).toHaveBeenCalledWith('attempt', 7, 1, 'in_progress', expect.any(Object), undefined, 'checkpoint'));
  });

  it('resumes at the server position and uses the server next sequence for the next checkpoint', async () => {
    render(<ReviewCoursePlayer snapshot={resumeSnapshot} attemptId="attempt" initialLessonPosition={1} initialNextSequence={7} onComplete={() => undefined} />);
    expect(screen.getByRole('button', { name: '2. Второй урок' })).toHaveAttribute('aria-current', 'step');
    fireEvent.click(screen.getByRole('button', { name: 'Завершить проверку' }));
    await waitFor(() => expect(progressMock).toHaveBeenCalledWith('attempt', 7, 1, 'in_progress', expect.objectContaining({ activity: 'review_completed' }), undefined, 'checkpoint'));
  });

  it('falls back safely for missing or invalid resume metadata and resets on identity change', async () => {
    const view = render(<ReviewCoursePlayer snapshot={resumeSnapshot} attemptId="attempt-a" initialLessonPosition={99} initialNextSequence={0} onComplete={() => undefined} />);
    expect(screen.getByRole('button', { name: '1. Урок' })).toHaveAttribute('aria-current', 'step');
    fireEvent.click(screen.getByRole('button', { name: '2. Второй урок' }));
    await waitFor(() => expect(progressMock).toHaveBeenCalledWith('attempt-a', 1, 1, 'in_progress', expect.any(Object), undefined, 'checkpoint'));
    view.rerender(<ReviewCoursePlayer snapshot={snapshot} attemptId="attempt-b" initialLessonPosition={null} initialNextSequence={undefined} onComplete={() => undefined} />);
    await waitFor(() => expect(screen.getByRole('button', { name: '1. Урок' })).toHaveAttribute('aria-current', 'step'));
  });

  it('renders lesson Markdown through the shared content renderer and suppresses only the duplicate title', () => {
    render(<ReviewCoursePlayer snapshot={resumeSnapshot} attemptId="attempt" initialLessonPosition={1} onComplete={() => undefined} />);
    expect(screen.queryByRole('heading', { level: 1, name: 'Второй урок' })).not.toBeInTheDocument();
    expect(screen.getByText('Текст второго урока')).toBeInTheDocument();
  });

  it('passes server resume metadata from the request screen into the player', async () => {
    getRequestMock.mockResolvedValue({ request_id: 'request', revision_id: 'revision', outcome: 'pending', delivery_mode: 'personal_link', reviewer_ids: ['reviewer'] });
    startAttemptMock.mockResolvedValue({ attempt_id: 'attempt-resume', revision_id: 'revision', snapshot_sha256: 'sha-resume', activity_state: 'in_progress', lesson_position: 1, next_sequence: 7, snapshot: resumeSnapshot });
    render(<ReviewRequestScreen requestId="request" onCompleted={() => undefined} />);
    expect(await screen.findByRole('button', { name: '2. Второй урок' })).toHaveAttribute('aria-current', 'step');
    fireEvent.click(screen.getByRole('button', { name: 'Завершить проверку' }));
    await waitFor(() => expect(progressMock).toHaveBeenCalledWith('attempt-resume', 7, 1, 'in_progress', expect.objectContaining({ activity: 'review_completed' }), undefined, 'checkpoint'));
  });

  it('shows an accessible completion confirmation after a successful decision', async () => {
    const onCompleted = vi.fn();
    getScopedRequestMock.mockResolvedValue({ request_id: 'request', revision_id: 'revision', outcome: 'pending', delivery_mode: 'personal_link', reviewer: { id: 'reviewer' } });
    startAttemptMock.mockResolvedValue({ attempt_id: 'attempt-decision', revision_id: 'revision', snapshot_sha256: 'sha-decision', activity_state: 'completed', snapshot });
    const view = render(<ReviewRequestScreen requestId="request" token="scoped-token" onCompleted={onCompleted} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Согласовать версию' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить решение' }));
    await waitFor(() => expect(decisionMock).toHaveBeenCalledWith('attempt-decision', 'approve', null, false, 'scoped-token'));
    expect(await screen.findByRole('status')).toHaveTextContent('Решение сохранено');
    expect(screen.getByText(/Проверка завершена/i)).toBeInTheDocument();
    expect(onCompleted).toHaveBeenCalledTimes(1);

    view.rerender(<ReviewRequestScreen requestId="request" onCompleted={onCompleted} />);
    expect(await screen.findByRole('status')).toHaveTextContent('Решение сохранено');
    expect(getScopedRequestMock).toHaveBeenCalledTimes(1);
    expect(getRequestMock).not.toHaveBeenCalled();
  });

  it('clears limited access and closes successful scoped review to ordinary login', async () => {
    replaceMock.mockReset();
    sessionStorage.setItem('course_review_token', 'test-scoped-token');
    getScopedRequestMock.mockResolvedValue({ request_id: 'request', revision_id: 'revision', outcome: 'pending', delivery_mode: 'personal_link', reviewer: { id: 'reviewer' } });
    startAttemptMock.mockResolvedValue({ attempt_id: 'attempt-close', revision_id: 'revision', snapshot_sha256: 'sha-close', activity_state: 'completed', snapshot });
    render(<ScopedReviewRequestPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Согласовать версию' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить решение' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Решение сохранено');
    expect(sessionStorage.getItem('course_review_token')).toBeNull();
    expect(replaceMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(replaceMock).toHaveBeenCalledExactlyOnceWith('/login');
  });

  it('does not show another capability the completed decision for the same request', async () => {
    getScopedRequestMock.mockResolvedValue({ request_id: 'request', revision_id: 'revision', outcome: 'pending', reviewer: { id: 'reviewer' } });
    startAttemptMock.mockResolvedValue({ attempt_id: 'attempt-a', snapshot_sha256: 'sha-a', activity_state: 'completed', snapshot });
    const view = render(<ReviewRequestScreen requestId="request" token="capability-a" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Согласовать версию' }));
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить решение' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Решение сохранено'));
    startAttemptMock.mockResolvedValue({ attempt_id: 'attempt-b', snapshot_sha256: 'sha-b', activity_state: 'completed', snapshot });
    view.rerender(<ReviewRequestScreen requestId="request" token="capability-b" />);
    await waitFor(() => expect(getScopedRequestMock).toHaveBeenLastCalledWith('capability-b', 'request'));
    expect(await screen.findByText('Снимок: sha-b')).toBeInTheDocument();
    expect(screen.queryByText('Решение сохранено')).not.toBeInTheDocument();
    getRequestMock.mockResolvedValue({ request_id: 'request', revision_id: 'revision', outcome: 'pending' });
    view.rerender(<ReviewRequestScreen requestId="request" />);
    await waitFor(() => expect(getRequestMock).toHaveBeenCalledWith('request'));
    expect(screen.queryByText('Решение сохранено')).not.toBeInTheDocument();
  });

  it('does not carry completion confirmation to a different request', async () => {
    getRequestMock.mockResolvedValue({ request_id: 'request', revision_id: 'revision', outcome: 'pending', delivery_mode: 'personal_link', reviewer_ids: ['reviewer'] });
    startAttemptMock.mockResolvedValue({ attempt_id: 'attempt-other', revision_id: 'revision', snapshot_sha256: 'sha-other', activity_state: 'completed', snapshot });
    const view = render(<ReviewRequestScreen requestId="request" onCompleted={() => undefined} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Согласовать версию' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить решение' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Решение сохранено'));

    getRequestMock.mockResolvedValue({ request_id: 'request-2', revision_id: 'revision-2', outcome: 'pending', delivery_mode: 'personal_link', reviewer_ids: ['reviewer'] });
    view.rerender(<ReviewRequestScreen requestId="request-2" onCompleted={() => undefined} />);
    expect(await screen.findByText('Проверка версии курса')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
