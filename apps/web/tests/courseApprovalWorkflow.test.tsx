import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const configureMock = vi.hoisted(() => vi.fn());
const decisionMock = vi.hoisted(() => vi.fn());
const progressMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/courseApproval', async () => {
  const actual = await vi.importActual<typeof import('@/lib/courseApproval')>('@/lib/courseApproval');
  return { ...actual, configureApprovalPolicy: configureMock, submitReviewDecision: decisionMock, saveReviewProgress: progressMock };
});
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ApprovalPolicyCard } from '@/components/course-approval/ApprovalPolicyCard';
import { ReviewerDecisionPanel } from '@/components/course-approval/ReviewerDecisionPanel';
import { ReviewCoursePlayer } from '@/components/course-approval/ReviewCoursePlayer';

const snapshot = { schema_version: 1, release_version: 3, course: { id: 'course', title: 'Курс' }, modules: [{ id: 'module', title: 'Модуль', lessons: [{ id: 'lesson', title: 'Урок', content_type: 'text', content: 'Текст', order_index: 0, quizzes: [{ id: 'quiz', title: 'Тест', pass_score: 80, questions: [{ id: 'question', text: 'Вопрос', type: 'single_choice', points: 1, choices: [{ id: 'choice-1', text: 'Правильный текст', order_index: 0 }] }] }] }] }] };

describe('course approval workflow UI', () => {
  beforeEach(() => { configureMock.mockReset().mockResolvedValue({ requires_approval: true }); decisionMock.mockReset().mockResolvedValue({}); progressMock.mockReset().mockResolvedValue({ diagnostics: { score_percent: 100, passed: true } }); });

  it('persists the opt-in policy and gives a clear immutable-snapshot hint', async () => {
    render(<ApprovalPolicyCard courseId="course" />);
    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(configureMock).toHaveBeenCalledWith('course', true));
    expect(screen.getByText(/неизменяемый снимок/i)).toBeInTheDocument();
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
    await waitFor(() => expect(progressMock).toHaveBeenCalledWith('attempt', 1, 0, 'in_progress', expect.objectContaining({ activity: 'quiz_submitted', answers: [{ question_id: 'question', choice_id: 'choice-1' }] }), undefined));
    expect(screen.getByRole('status')).toHaveTextContent('100%');
  });
});
