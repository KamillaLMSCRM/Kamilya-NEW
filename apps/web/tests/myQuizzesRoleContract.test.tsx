import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'common.loading': 'Loading',
      'common.loadFailed': 'Could not load quizzes',
      'common.retry': 'Retry',
      'student.myQuizzes': 'My quizzes',
      'student.totalQuizzes': 'Total quizzes',
      'student.pendingQuizzes': 'Pending',
      'student.passedQuizzes': 'Passed',
      'student.toComplete': 'To complete',
      'student.pendingBadge': 'Pending',
      'student.takeQuiz': 'Take quiz',
      'student.completedQuizzes': 'Completed quizzes',
      'student.passedOn': 'Passed on',
      'student.noQuizzes': 'No quizzes',
      'student.browseCourses': 'Browse courses',
      'quiz.passScore': 'Pass score',
      'quiz.deferralDays': 'Deferral',
      'quiz.attempts': 'Attempts',
      'quiz.expiredHint': 'Expired after {daysText}',
      'quiz.expired': 'Expired',
      'quiz.notAvailable': 'Not available',
    }[key] ?? key),
    tp: (key: string, value: number) => `${value} days`,
  }),
}));

import MyQuizzesPage from '@/app/my-quizzes/page';

const pendingQuiz = {
  quiz_id: 'quiz-1',
  quiz_title: 'Safety quiz',
  lesson_title: 'Lesson 1',
  module_title: 'Module 1',
  course_id: 'course-1',
  pass_score: 80,
  deferral_days: 7,
  attempt_limit: 2,
  score_percent: null,
  passed: false,
  completed_at: null,
  attempts_count: 0,
  is_expired: false,
};

const expiredQuiz = { ...pendingQuiz, quiz_id: 'quiz-expired', is_expired: true };

describe('my quizzes student role contract', () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.get.mockResolvedValue({ data: [pendingQuiz, expiredQuiz] });
  });

  it('keeps pending quiz navigation and expired quizzes disabled', async () => {
    render(<MyQuizzesPage />);

    expect(await screen.findByRole('link', { name: 'Take quiz' })).toHaveAttribute('href', '/courses/quiz/quiz-1');
    expect(screen.getByRole('button', { name: 'Not available' })).toBeDisabled();
  });

  it('uses the learner-owned route for the empty-state CTA', async () => {
    apiMock.get.mockResolvedValue({ data: [] });
    render(<MyQuizzesPage />);

    expect(await screen.findByRole('link', { name: 'Browse courses' })).toHaveAttribute('href', '/my-courses');
  });

  it('shows a localized error and retries successfully after an API failure', async () => {
    apiMock.get
      .mockRejectedValueOnce(new Error('request failed'))
      .mockResolvedValueOnce({ data: [pendingQuiz] });
    render(<MyQuizzesPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load quizzes');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('link', { name: 'Take quiz' })).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledTimes(2);
  });
});
