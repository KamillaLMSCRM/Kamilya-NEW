import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const configureMock = vi.hoisted(() => vi.fn());
const getPolicyMock = vi.hoisted(() => vi.fn());
const decisionMock = vi.hoisted(() => vi.fn());
const progressMock = vi.hoisted(() => vi.fn());
const testMock = vi.hoisted(() => vi.fn());
const getRequestMock = vi.hoisted(() => vi.fn());
const startAttemptMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/courseApproval', async () => {
  const actual = await vi.importActual<typeof import('@/lib/courseApproval')>('@/lib/courseApproval');
  return { ...actual, configureApprovalPolicy: configureMock, getApprovalPolicy: getPolicyMock, submitReviewDecision: decisionMock, saveReviewProgress: progressMock, submitReviewTest: testMock, getApprovalRequest: getRequestMock, startReviewAttempt: startAttemptMock };
});
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ApprovalPolicyCard } from '@/components/course-approval/ApprovalPolicyCard';
import { ReviewerDecisionPanel } from '@/components/course-approval/ReviewerDecisionPanel';
import { ReviewCoursePlayer } from '@/components/course-approval/ReviewCoursePlayer';
import { ReviewRequestScreen } from '@/components/course-approval/ReviewRequestScreen';

const snapshot = { schema_version: 1, release_version: 3, course: { id: 'course', title: 'Курс' }, modules: [{ id: 'module', title: 'Модуль', order_index: 0, lessons: [{ id: 'lesson', title: 'Урок', content_type: 'text', content: 'Текст', order_index: 0, quizzes: [{ id: 'quiz', title: 'Тест', pass_score: 80, questions: [{ id: 'question', text: 'Вопрос', type: 'single_choice', points: 1, order_index: 0, choices: [{ id: 'choice-1', text: 'Правильный текст', order_index: 0 }] }] }] }] }] };
const resumeSnapshot = { ...snapshot, release_version: 4, modules: [{ ...snapshot.modules[0], lessons: [snapshot.modules[0].lessons[0], { id: 'lesson-2', title: 'Второй урок', content_type: 'text', content: '# Второй урок\n\nТекст второго урока', order_index: 1, quizzes: [] }] }] };

describe('course approval workflow UI', () => {
  beforeEach(() => { configureMock.mockReset().mockResolvedValue({ requires_approval: true, review_enabled: true }); getPolicyMock.mockReset().mockResolvedValue({ requires_approval: false, review_enabled: true }); decisionMock.mockReset().mockResolvedValue({}); progressMock.mockReset().mockResolvedValue({}); testMock.mockReset().mockResolvedValue({ diagnostics: { answered: 1, total: 1, correct: 1, score_percent: 100, complete: true } }); getRequestMock.mockReset(); startAttemptMock.mockReset(); });

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
    await waitFor(() => expect(decisionMock).toHaveBeenCalledWith('attempt', 'approve', null, true, undefined));
  });

  it('renders the reviewer snapshot structurally without answer-key fields', () => {
    render(<ReviewCoursePlayer snapshot={snapshot} attemptId="attempt" onComplete={() => undefined} />);
    expect(screen.getByText('Правильный текст')).toBeInTheDocument();
    expect(screen.queryByText(/is_correct/i)).not.toBeInTheDocument();
    expect(screen.getByText('Режим проверки')).toBeInTheDocument();
  });

  it('sends interactive quiz answers only through the review progress endpoint', async () => {
    render(<ReviewCoursePlayer snapshot={snapshot} attemptId="attempt" onComplete={() => undefined} />);
    fireEvent.click(screen.getByLabelText('Правильный текст'));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ответы' }));
    await waitFor(() => expect(testMock).toHaveBeenCalledWith('attempt', [{ question_id: 'question', selected_choice_ids: ['choice-1'] }], undefined));
    expect(screen.getByRole('status')).toHaveTextContent('100%');
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
});
