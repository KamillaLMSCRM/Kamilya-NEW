import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const routerPush = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'course-1' }),
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ back: vi.fn(), push: routerPush, replace: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'courses.nextLesson': 'Следующий урок',
      'courses.markComplete': 'Урок завершён',
      'quiz.startQuiz': 'Начать тест',
      'quiz.passScore': 'Проходной балл',
      'quiz.attempts': 'Попытки',
      'quiz.deferralDays': 'Повтор через дней',
      'toast.coursePreviewCompleted': 'Предпросмотр курса завершён',
    }[key] || key),
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  toast: { dismiss: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

vi.mock('@/lib/useIdleTimeout', () => ({
  useIdleTimeout: () => ({ warningSeconds: null }),
}));

import CoursePlayerPage from '@/app/courses/[id]/page';
import { useAuthStore } from '@/store/authStore';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const course = {
  id: 'course-1',
  title: 'Черновой курс',
  description: 'Предпросмотр',
  status: 'draft',
  delivery_type: 'native',
};

const lesson = {
  id: 'lesson-1',
  title: 'Шестой урок',
  content_type: 'text',
  content: 'Материал урока',
  order_index: 0,
};

function setupFetch() {
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/v1/courses/course-1')) return jsonResponse(course);
    if (url.endsWith('/v1/courses/course-1/structure')) {
      return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons: [lesson] }] });
    }
    if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) {
      return jsonResponse({ completed_lesson_ids: ['lesson-1'] });
    }
    if (url.endsWith('/v1/student/dashboard')) {
      return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_status: 'in_progress' }] });
    }
    if (url.endsWith('/v1/quizzes/by-lesson/lesson-1')) {
      return jsonResponse({
        id: 'quiz-1', title: 'Проверка урока', pass_score: 80,
        time_limit: null, attempt_limit: 3, deferral_days: 0,
      });
    }
    if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return jsonResponse([]);
    if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
    if (url.endsWith('/v1/courses/course-1/complete') && init?.method === 'POST') {
      return jsonResponse({ detail: 'Course must have an immutable ContentRelease before completion' }, 400);
    }
    return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
}

describe('course player role modes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupFetch();
  });

  it('finishes a methodologist preview without calling learner course completion', async () => {
    useAuthStore.setState({
      accessToken: 'methodologist-token',
      user: { id: 'methodologist-1', role: 'methodologist' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    await screen.findByText('Проверка урока');
    fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' }));

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith('/courses'));
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/course-1/complete'),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('does not let a learner skip an unpassed required quiz', async () => {
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    await screen.findByText('Проверка урока');
    expect(screen.getByRole('button', { name: 'Начать тест' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Следующий урок' })).not.toBeInTheDocument();
  });
});
