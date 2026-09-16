import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const routerPushMock = vi.hoisted(() => vi.fn());

vi.mock('next/navigation', () => ({
  useParams: () => ({ quizId: 'quiz-1' }),
  useSearchParams: () => new URLSearchParams('courseId=course-1&lessonId=lesson-1'),
  useRouter: () => ({ back: vi.fn(), push: routerPushMock, replace: vi.fn() }),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'courses.backToCourse': 'Вернуться к курсу',
      'courses.nextLesson': 'Следующий урок',
    }[key] || key),
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  toast: { dismiss: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

import QuizPlayerPage from '@/app/courses/quiz/[quizId]/page';
import { useAuthStore } from '@/store/authStore';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const quiz = {
  id: 'quiz-1',
  lesson_id: 'lesson-1',
  title: 'Проверка урока',
  pass_score: 50,
  time_limit: null,
  attempt_limit: 3,
  questions: [{
    id: 'question-1',
    text: 'Верный ответ?',
    type: 'MCQ',
    points: 1,
    explanation: null,
    order_index: 0,
    choices: [{ id: 'choice-1', text: 'Да', order_index: 0 }],
  }],
};

let quizPayload = quiz;
let previousAttempts: QuizAttemptFixture[] = [];
let structureLessons = [
  { id: 'lesson-1', title: 'Первый урок', order_index: 0 },
  { id: 'lesson-2', title: 'Следующий урок', order_index: 1 },
];

interface QuizAttemptFixture {
  id: string;
  score_percent: number;
  passed: boolean;
  started_at: string;
  completed_at: string | null;
}

describe('learner quiz result navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    quizPayload = quiz;
    previousAttempts = [];
    structureLessons = [
      { id: 'lesson-1', title: 'Первый урок', order_index: 0 },
      { id: 'lesson-2', title: 'Следующий урок', order_index: 1 },
    ];
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', email: 'student@example.com', role: 'student' } as never,
      initialized: true,
    });
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/quizzes/quiz-1') && init?.method !== 'POST') return jsonResponse(quizPayload);
      if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return jsonResponse(previousAttempts);
      if (url.endsWith('/v1/courses/course-1/structure')) {
        return jsonResponse({ modules: [{ lessons: structureLessons }] });
      }
      if (url.endsWith('/v1/quizzes/quiz-1/submit')) {
        return jsonResponse({
          attempt: {
            id: 'attempt-1', quiz_id: 'quiz-1', user_id: 'student-1',
            score_percent: 100, total_points: 1, earned_points: 1,
            passed: true, answers: [], started_at: '', completed_at: '', time_spent_seconds: 1,
          },
          correct_answers: 1, total_questions: 1, passed: true, message: 'Тест пройден',
        });
      }
      return jsonResponse({ detail: 'Unexpected request' }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('returns to the parent course and offers the next lesson after a passed quiz', async () => {
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));

    await waitFor(() => expect(screen.getByText('Тест пройден')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'Вернуться к курсу' })).toHaveAttribute(
      'href', '/courses/course-1?lessonId=lesson-1',
    );
    expect(screen.getByRole('link', { name: 'Следующий урок' })).toHaveAttribute(
      'href', '/courses/course-1?lessonId=lesson-2',
    );
  });

  it('keeps the learner SPA session when the final lesson is completed', async () => {
    structureLessons = [{ id: 'lesson-1', title: 'Первый урок', order_index: 0 }];
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));

    const finishButton = await screen.findByRole('button', { name: 'Вернуться в курс и завершить' });
    fireEvent.click(finishButton);

    expect(routerPushMock).toHaveBeenCalledWith('/courses/course-1?lessonId=lesson-1');
  });

  it('rotates MCQ choices between attempts while keeping their ids selectable', async () => {
    quizPayload = {
      ...quiz,
      questions: [{
        ...quiz.questions[0],
        order_index: 1,
        choices: [
          { id: 'choice-a', text: 'Вариант A', order_index: 0 },
          { id: 'choice-b', text: 'Вариант B', order_index: 1 },
          { id: 'choice-c', text: 'Вариант C', order_index: 2 },
          { id: 'choice-d', text: 'Вариант D', order_index: 3 },
        ],
      }],
    };
    previousAttempts = [{
      id: 'attempt-previous',
      score_percent: 25,
      passed: false,
      started_at: '2026-09-13T00:00:00Z',
      completed_at: '2026-09-13T00:01:00Z',
    }];

    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    const labels = screen.getAllByRole('radio').map((radio) => radio.parentElement?.textContent);
    expect(labels).toEqual(['Вариант B', 'Вариант C', 'Вариант D', 'Вариант A']);
    fireEvent.click(screen.getAllByRole('radio')[0]);
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/quizzes/quiz-1/submit'),
      expect.objectContaining({ body: expect.stringContaining('choice-b') }),
    ));
  });
});
