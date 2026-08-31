import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
      'courses.finishCourse': 'Завершить курс',
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
import { isTrustedScormBridgeMessage } from '@/features/scorm/bridge';
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

function setupFetch(
  accessWindow: unknown = null,
  lessonContent = lesson.content,
  courseOverride: typeof course = course,
) {
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/v1/courses/course-1')) return jsonResponse(courseOverride);
    if (url.endsWith('/v1/courses/course-1/structure')) {
      return jsonResponse({
        modules: [{
          id: 'module-1',
          title: 'Модуль',
          description: '',
          order_index: 0,
          lessons: [{ ...lesson, content: lessonContent }],
        }],
      });
    }
    if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) {
      return jsonResponse({ completed_lesson_ids: ['lesson-1'] });
    }
    if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(accessWindow);
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
    cleanup();
    vi.clearAllMocks();
    fetchMock.mockReset();
    routerPush.mockReset();
    useAuthStore.setState({ accessToken: null, user: null, initialized: true });
    setupFetch();
  });

  it('shows a terminal completion action instead of a no-op next lesson button', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons: [lesson] }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: ['lesson-1'] });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_id: 'enrollment-1', enrollment_status: 'in_progress' }] });
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-1')) return jsonResponse({ id: 'quiz-1', title: 'Проверка урока', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 });
      if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return jsonResponse([{ id: 'attempt-1', score_percent: 100, passed: true }]);
      if (url.endsWith('/v1/courses/course-1/complete') && init?.method === 'POST') return jsonResponse({ status: 'completed', certificate_id: 'certificate-1', training_evidence_event_id: 'event-1' });
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    const finish = await screen.findByRole('button', { name: 'Завершить курс' });
    expect(screen.queryByRole('button', { name: 'Следующий урок' })).not.toBeInTheDocument();
    await act(async () => {
      finish.click();
    });
    expect(routerPush).not.toHaveBeenCalledWith('/courses');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/course-1/complete'),
      expect.objectContaining({ method: 'POST' }),
    ));
  });

  it('finishes a methodologist preview without calling learner course completion', async () => {
    useAuthStore.setState({
      accessToken: 'methodologist-token',
      user: { id: 'methodologist-1', role: 'methodologist' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    await screen.findByText('Проверка урока');
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' }));
    });

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

  it('renders persisted lesson markup as safe text while preserving basic emphasis', async () => {
    setupFetch(
      null,
      'Безопасный **жирный** текст\n<img src=x onerror="alert(1)"><script>alert(2)</script><a href="javascript:alert(3)">ссылка</a>',
    );
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    expect(await screen.findByText('жирный')).toHaveProperty('tagName', 'STRONG');
    expect(document.body.textContent).toContain('<img src=x onerror="alert(1)">');
    expect(document.querySelector('img[src="x"]')).not.toBeInTheDocument();
    expect(document.querySelector('script')).not.toBeInTheDocument();
    expect(document.querySelector('a[href^="javascript:"]')).not.toBeInTheDocument();
  });

  it('shows a server-anchored assignment countdown that survives page reloads', async () => {
    setupFetch({
      server_now: '2026-08-13T09:00:00Z',
      access_policy: {
        enrollment_id: 'enrollment-1',
        delivery_mode: 'personal_link',
        completion_window_started_at: '2026-08-13T09:00:00Z',
        completion_window_expires_at: '2026-08-13T09:30:00Z',
        due_at: null,
        state: 'available',
      },
    });
    useAuthStore.setState({
      accessToken: 'assignment-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    expect(await screen.findByRole('timer')).toHaveTextContent('Оставшееся время на курс и тест');
    expect(screen.getByRole('timer')).toHaveTextContent(/00:29:5\d|00:30:00/);
    expect(screen.getByText('Таймер не сбрасывается при обновлении страницы.')).toBeInTheDocument();
  });

  it('blocks learner actions when the assignment window is expired', async () => {
    setupFetch({
      server_now: '2026-08-13T09:31:00Z',
      access_policy: {
        enrollment_id: 'enrollment-1',
        delivery_mode: 'personal_link',
        completion_window_started_at: '2026-08-13T09:00:00Z',
        completion_window_expires_at: '2026-08-13T09:30:00Z',
        due_at: null,
        state: 'expired',
      },
    });
    useAuthStore.setState({
      accessToken: 'assignment-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Время, отведённое на прохождение, истекло');
    expect(screen.getByRole('button', { name: 'Начать тест' })).toBeDisabled();
  });

  it('embeds SCORM only from the dedicated origin with a restrictive sandbox', async () => {
    const scormCourse = { ...course, delivery_type: 'scorm' as const };
    setupFetch(null, lesson.content, scormCourse);
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse(scormCourse);
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) {
        return jsonResponse({ completed_lesson_ids: [] });
      }
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) {
        return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_status: 'in_progress' }] });
      }
      if (url.endsWith('/v1/scorm/courses/course-1/launch')) {
        return jsonResponse({
          course_id: 'course-1',
          package_id: 'package-1',
          launch_url: 'https://scorm.kml.kz/api/v1/scorm/packages/package-1/launch?token=opaque',
          launch_origin: 'https://scorm.kml.kz',
          bridge_channel: 'channel-123',
          version: 'scorm_1_2',
          title: 'SCORM курс',
        });
      }
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    const frame = await screen.findByTitle('Черновой курс');
    expect(frame).toHaveAttribute('src', expect.stringMatching(/^https:\/\/scorm\.kml\.kz\//));
    expect(frame).toHaveAttribute('sandbox', 'allow-forms allow-same-origin allow-scripts');
    expect(frame).not.toHaveAttribute('allow', expect.stringContaining('camera'));
  });

  it('accepts SCORM bridge messages only from the expected frame, origin, version, and channel', () => {
    const expectedSource = {} as Window;
    const valid = {
      origin: 'https://scorm.kml.kz',
      source: expectedSource,
      data: {
        version: 1,
        type: 'kamilya.scorm.status',
        channel: 'channel-123',
        status: 'saved',
      },
    } as MessageEvent;

    expect(isTrustedScormBridgeMessage(valid, {
      origin: 'https://scorm.kml.kz',
      channel: 'channel-123',
      source: expectedSource,
    })).toBe(true);
    expect(isTrustedScormBridgeMessage(
      { ...valid, origin: 'https://evil.example' } as MessageEvent,
      { origin: 'https://scorm.kml.kz', channel: 'channel-123', source: expectedSource },
    )).toBe(false);
    expect(isTrustedScormBridgeMessage(
      { ...valid, data: { ...valid.data, version: 2 } } as MessageEvent,
      { origin: 'https://scorm.kml.kz', channel: 'channel-123', source: expectedSource },
    )).toBe(false);
    expect(isTrustedScormBridgeMessage(
      { ...valid, data: { ...valid.data, channel: 'other' } } as MessageEvent,
      { origin: 'https://scorm.kml.kz', channel: 'channel-123', source: expectedSource },
    )).toBe(false);
    expect(isTrustedScormBridgeMessage(
      { ...valid, source: {} as Window } as MessageEvent,
      { origin: 'https://scorm.kml.kz', channel: 'channel-123', source: expectedSource },
    )).toBe(false);
  });
});
