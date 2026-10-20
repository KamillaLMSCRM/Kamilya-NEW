import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const routerPush = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const searchParamsState = vi.hoisted(() => ({ current: new URLSearchParams() }));
const courseRouteState = vi.hoisted(() => ({ current: 'course-1' }));
const translateMock = vi.hoisted(() => (key: string) => ({
  'courses.nextLesson': 'Следующий урок',
  'courses.finishCourse': 'Завершить курс',
  'courses.markComplete': 'Урок завершён',
  'quiz.startQuiz': 'Начать тест',
  'quiz.passScore': 'Проходной балл',
  'quiz.attempts': 'Попытки',
  'quiz.deferralDays': 'Повтор через дней',
  'common.loadFailed': 'Не удалось загрузить',
  'common.retry': 'Повторить',
  'toast.coursePreviewCompleted': 'Предпросмотр курса завершён',
  'authenticatedUi.player.timeExpiredTitle': 'Время, отведённое на прохождение, истекло',
  'authenticatedUi.player.timeExpiredDescription': 'Материалы и тестирование закрыты. Обратитесь к методисту, чтобы получить новое окно доступа.',
  'authenticatedUi.player.timeRemaining': 'Оставшееся время на курс и тест',
  'authenticatedUi.player.timerHint': 'Таймер не сбрасывается при обновлении страницы.',
}[key] || key));
const translatePluralMock = vi.hoisted(() => (key: string, count: number) => `${count} ${key}`);

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: courseRouteState.current }),
  useSearchParams: () => searchParamsState.current,
  useRouter: () => ({ back: vi.fn(), push: routerPush, replace: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: translateMock,
    tp: translatePluralMock,
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  toast: { dismiss: vi.fn(), success: toastSuccess, error: vi.fn() },
}));

vi.mock('@/lib/useIdleTimeout', () => ({
  useIdleTimeout: () => ({ warningSeconds: null }),
}));

vi.mock('@/features/training-evidence/EvidenceConfirmationPanel', () => ({
  EvidenceConfirmationPanel: ({ eventId }: { eventId: string }) => (
    <div data-testid="completion-evidence-event">{eventId}</div>
  ),
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
    if (url.includes('/v1/progress/lessons/') && init?.method === 'PUT') return jsonResponse({ completed: true });
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
    toastSuccess.mockReset();
    searchParamsState.current = new URLSearchParams();
    courseRouteState.current = 'course-1';
    useAuthStore.setState({ accessToken: null, user: null, initialized: true });
    setupFetch();
  });

  it.each(['methodologist', 'student'])('keeps lesson reading space before showing a side-by-side assistant for %s', async (role) => {
    useAuthStore.setState({ accessToken: 'reader-token', user: { id: 'reader-1', role } as never, initialized: true });
    render(<CoursePlayerPage />);
    await screen.findByRole('heading', { name: 'Шестой урок' });
    const assistant = screen.getByRole('heading', { name: 'authenticatedUi.player.assistantTitle' }).closest('aside')!;
    const readingLayout = assistant.parentElement!;
    // At a 1280px laptop, global and course navigation already take 560px.
    // The assistant must stack below, not consume another 340px of that row.
    expect(readingLayout).toHaveClass('grid-cols-1', '2xl:grid-cols-[minmax(0,1fr)_340px]');
    expect(readingLayout).not.toHaveClass('xl:grid-cols-[minmax(0,1fr)_340px]');
    expect(assistant).toBeVisible();
    expect(screen.getByText('Материал урока')).toBeVisible();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST' || init?.method === 'PUT')).toHaveLength(0);
  });

  it.each(['completed', 'in_progress', 'unassigned'])('returns the %s learner to their assigned-course list', async (state) => {
    setupFetch(null, lesson.content, { ...course, status: 'published' });
    const baseFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/v1/student/dashboard')) {
        return Promise.resolve(jsonResponse({ enrolled_courses: state === 'unassigned' ? [] : [{ course_id: 'course-1', enrollment_status: state }] }));
      }
      return baseFetch(input, init);
    });
    useAuthStore.setState({ accessToken: 'student-token', user: { id: 'student-1', role: 'student' } as never, initialized: true });
    render(<CoursePlayerPage />);

    const label = state === 'in_progress' ? 'courses.title' : 'courses.backToCourses';
    expect(await screen.findByRole('link', { name: label })).toHaveAttribute('href', '/my-courses');
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST' || init?.method === 'PUT')).toHaveLength(0);
  });

  it.each(['methodologist', 'admin', 'superadmin', 'student'])('clears a completed learner screen before loading the next %s identity', async (role) => {
    const baseFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const oldActor = (init?.headers as Record<string, string>)?.Authorization === 'Bearer student-old-token';
      if (url.endsWith('/v1/student/dashboard')) return Promise.resolve(jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_id: oldActor ? 'enrollment-old' : 'enrollment-new', enrollment_status: oldActor ? 'completed' : 'in_progress' }] }));
      if (url.includes('/v1/training-evidence/events/mine?')) return Promise.resolve(jsonResponse([{ id: 'evidence-old' }]));
      return baseFetch(input, init);
    });
    useAuthStore.setState({ accessToken: 'student-old-token', user: { user_id: 'student-old', role: 'student' } as never, initialized: true });
    const view = render(<CoursePlayerPage />);
    expect(await screen.findByTestId('completion-evidence-event')).toHaveTextContent('evidence-old');

    await act(async () => {
      useAuthStore.setState({ accessToken: 'new-token', user: { user_id: 'new-identity', role } as never, initialized: true });
      view.rerender(<CoursePlayerPage />);
    });
    await screen.findByRole('heading', { name: 'Шестой урок' });
    expect(screen.queryByTestId('completion-evidence-event')).not.toBeInTheDocument();
    expect(screen.queryByText('evidence-old')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST' || init?.method === 'PUT')).toHaveLength(0);
  });

  it('ignores a delayed completion response after the learner identity changes', async () => {
    let resolveCompletion!: (response: Response) => void;
    const baseFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return Promise.resolve(jsonResponse([{ score_percent: 100, passed: true }]));
      if (url.endsWith('/v1/courses/course-1/complete') && init?.method === 'POST') return new Promise(resolve => { resolveCompletion = resolve; });
      return baseFetch(input, init);
    });
    useAuthStore.setState({ accessToken: 'student-old-token', user: { user_id: 'student-old', role: 'student' } as never, initialized: true });
    const view = render(<CoursePlayerPage />);
    await screen.findByText('quiz.passed (100%)');
    fireEvent.click(screen.getByRole('button', { name: 'Завершить курс' }));
    await waitFor(() => expect(resolveCompletion).toBeTypeOf('function'));
    await act(async () => {
      useAuthStore.setState({ accessToken: 'student-new-token', user: { user_id: 'student-new', role: 'student' } as never, initialized: true });
      view.rerender(<CoursePlayerPage />);
    });
    await screen.findByRole('heading', { name: 'Шестой урок' });
    await act(async () => resolveCompletion(jsonResponse({ status: 'completed', certificate_id: 'old-certificate', training_evidence_event_id: 'old-evidence' })));
    expect(screen.queryByTestId('completion-evidence-event')).not.toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalledWith('toast.courseCompleted');
    expect(routerPush).not.toHaveBeenCalled();
  });

  it.each([200, 503])('ignores a delayed assistant HTTP%s result after the learner identity changes', async (status) => {
    let resolveReply!: (response: Response) => void;
    const baseFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith('/v1/learner/assistant/chat')
      ? new Promise(resolve => { resolveReply = resolve; }) : baseFetch(input, init));
    useAuthStore.setState({ accessToken: 'student-old-token', user: { user_id: 'student-old', role: 'student' } as never, initialized: true });
    const view = render(<CoursePlayerPage />);
    await screen.findByRole('heading', { name: 'Шестой урок' });
    fireEvent.change(screen.getByPlaceholderText('authenticatedUi.player.assistantPlaceholder'), { target: { value: 'Old learner question' } });
    fireEvent.click(screen.getByRole('button', { name: 'authenticatedUi.player.ask' }));
    await waitFor(() => expect(resolveReply).toBeTypeOf('function'));
    await act(async () => {
      useAuthStore.setState({ accessToken: 'student-new-token', user: { user_id: 'student-new', role: 'student' } as never, initialized: true });
      view.rerender(<CoursePlayerPage />);
    });
    await screen.findByRole('heading', { name: 'Шестой урок' });
    await act(async () => resolveReply(jsonResponse(status === 200 ? { reply: 'Old learner private reply' } : { detail: 'Old learner request error' }, status)));
    expect(screen.queryByText('Old learner private reply')).not.toBeInTheDocument();
    expect(screen.queryByText(/Old learner request error/)).not.toBeInTheDocument();
    expect(screen.queryByText('Old learner question')).not.toBeInTheDocument();
  });

  it.each([true, false])('shows a terminal completion action with evidence=%s instead of a no-op next lesson button', async (hasEvidence) => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons: [lesson] }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: ['lesson-1'] });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_id: 'enrollment-1', enrollment_status: 'in_progress' }] });
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-1')) return jsonResponse({ id: 'quiz-1', title: 'Проверка урока', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 });
      if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return jsonResponse([{ id: 'attempt-1', score_percent: 100, passed: true }]);
      if (url.endsWith('/v1/progress/lessons/lesson-1') && init?.method === 'PUT') return jsonResponse({ completed: true });
      if (url.endsWith('/v1/courses/course-1/complete') && init?.method === 'POST') return jsonResponse({ status: 'completed', certificate_id: 'certificate-1', ...(hasEvidence ? { training_evidence_event_id: 'event-1' } : {}) });
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    await screen.findByText('quiz.passed (100%)');
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
    if (!hasEvidence) await waitFor(() => expect(routerPush).toHaveBeenCalledWith('/my-courses'));
  });

  it('stacks the course outline above lesson content on narrow screens', async () => {
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    await screen.findByRole('heading', { name: 'Шестой урок' });
    const root = document.querySelector('div.min-h-screen');
    const outline = root?.querySelector('div.w-full');
    const content = root?.querySelector('div.min-w-0');
    expect(root).toHaveClass('flex-col', 'md:flex-row');
    expect(outline).toHaveClass('w-full', 'md:w-80');
    expect(content).toBeInTheDocument();
  });

  it('persists the current lesson before moving to the next lesson without a manual confirmation action', async () => {
    const lessons = [lesson, { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 }];
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: [] });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_id: 'enrollment-1', enrollment_status: 'in_progress' }] });
      if (url.includes('/v1/quizzes/by-lesson/')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.endsWith('/v1/progress/lessons/lesson-1') && init?.method === 'PUT') return jsonResponse({ completed: true });
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'student-token', user: { id: 'student-1', role: 'student' } as never, initialized: true });

    render(<CoursePlayerPage />);

    expect(await screen.findByRole('button', { name: 'Следующий урок' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Урок завершён' })).not.toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' })));

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith('/courses/course-1?lessonId=lesson-2'));
    const progressCall = fetchMock.mock.calls.findIndex(([input, init]) => String(input).endsWith('/v1/progress/lessons/lesson-1') && init?.method === 'PUT');
    const navigationCall = routerPush.mock.invocationCallOrder[0];
    expect(progressCall).toBeGreaterThanOrEqual(0);
    expect(navigationCall).toBeGreaterThan(fetchMock.mock.invocationCallOrder[progressCall]);
  });

  it('persists the last lesson before requesting server-side course completion', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons: [lesson] }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: [] });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_id: 'enrollment-1', enrollment_status: 'in_progress' }] });
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-1')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.endsWith('/v1/progress/lessons/lesson-1') && init?.method === 'PUT') return jsonResponse({ completed: true });
      if (url.endsWith('/v1/courses/course-1/complete') && init?.method === 'POST') return jsonResponse({ status: 'completed', training_evidence_event_id: 'event-1' });
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'student-token', user: { id: 'student-1', role: 'student' } as never, initialized: true });

    render(<CoursePlayerPage />);
    const finish = await screen.findByRole('button', { name: 'Завершить курс' });
    await act(async () => fireEvent.click(finish));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/v1/courses/course-1/complete'), expect.objectContaining({ method: 'POST' })));
    const progressOrder = fetchMock.mock.invocationCallOrder.find((order, index) => String(fetchMock.mock.calls[index][0]).endsWith('/v1/progress/lessons/lesson-1'));
    const completionOrder = fetchMock.mock.invocationCallOrder.find((order, index) => String(fetchMock.mock.calls[index][0]).endsWith('/v1/courses/course-1/complete'));
    expect(progressOrder).toBeDefined();
    expect(completionOrder).toBeDefined();
    expect(progressOrder as number).toBeLessThan(completionOrder as number);
  });

  it('finishes a methodologist preview without calling learner course completion', async () => {
    useAuthStore.setState({
      accessToken: 'methodologist-token',
      user: { id: 'methodologist-1', role: 'methodologist' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    await screen.findByText('Проверка урока');
    expect(screen.getByRole('link', { name: 'Начать тест' })).toHaveAttribute(
      'href',
      '/courses/quiz/quiz-1/preview?courseId=course-1&lessonId=lesson-1',
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' }));
    });

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith('/courses'));
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/course-1/complete'),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('renders the next preview lesson when the URL already names that lesson', async () => {
    const lessons = [lesson, { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 }];
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse(course);
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: [] });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.includes('/v1/quizzes/by-lesson/')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      if (url.includes('/v1/progress/lessons/') || url.includes('/v1/courses/course-1/complete')) {
        throw new Error(`Unexpected preview mutation: ${url}`);
      }
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'methodologist-token', user: { user_id: 'methodologist-1', role: 'methodologist' } as never, initialized: true });
    searchParamsState.current = new URLSearchParams('lessonId=lesson-2');

    render(<CoursePlayerPage />);
    expect(await screen.findByRole('heading', { name: 'Следующий урок' })).toBeInTheDocument();
    fireEvent.click(screen.getAllByText('Шестой урок')[0]);
    expect(await screen.findByRole('heading', { name: 'Шестой урок' })).toBeInTheDocument();

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' })));

    expect(routerPush).not.toHaveBeenCalledWith('/courses/course-1?lessonId=lesson-2');
    expect(screen.getByRole('heading', { name: 'Следующий урок' })).toBeInTheDocument();
  });

  it('clears the previous lesson quiz while the next quiz loads and ignores late attempts', async () => {
    const lessons = [
      lesson,
      { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 },
      { ...lesson, id: 'lesson-3', title: 'Последний урок', order_index: 2 },
    ];
    let resolveSecondQuiz!: (response: Response) => void;
    let resolveSecondAttempts!: (response: Response) => void;
    let secondRequestSnapshot: { oldQuiz: boolean; oldPass: boolean; oldLink: boolean } | null = null;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: lessons.map(({ id }) => id) });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_status: 'in_progress' }] });
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-1')) return jsonResponse({ id: 'quiz-1', title: 'Старый тест', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 });
      if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return jsonResponse([{ id: 'attempt-1', score_percent: 100, passed: true }]);
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-2')) {
        secondRequestSnapshot = {
          oldQuiz: screen.queryByText('Старый тест') !== null,
          oldPass: screen.queryByText('quiz.passed (100%)') !== null,
          oldLink: screen.queryByRole('link', { name: 'Начать тест' }) !== null,
        };
        return new Promise(resolve => { resolveSecondQuiz = resolve; });
      }
      if (url.endsWith('/v1/quizzes/quiz-2/attempts')) return new Promise(resolve => { resolveSecondAttempts = resolve; });
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-3')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'student-token', user: { user_id: 'student-1', role: 'student' } as never, initialized: true });

    render(<CoursePlayerPage />);
    expect(await screen.findByText('Старый тест')).toBeInTheDocument();
    expect(await screen.findByText('quiz.passed (100%)')).toBeInTheDocument();

    await act(async () => fireEvent.click(screen.getAllByText('Следующий урок')[0]));
    await waitFor(() => expect(resolveSecondQuiz).toBeTypeOf('function'));
    expect(secondRequestSnapshot).toEqual({ oldQuiz: false, oldPass: false, oldLink: false });
    expect(screen.queryByText('Старый тест')).not.toBeInTheDocument();
    expect(screen.queryByText('quiz.passed (100%)')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Начать тест' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Следующий урок' })).not.toBeInTheDocument();

    await act(async () => resolveSecondQuiz(jsonResponse({ id: 'quiz-2', title: 'Новый тест', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 })));
    await waitFor(() => expect(resolveSecondAttempts).toBeTypeOf('function'));
    expect(screen.queryByText('Новый тест')).not.toBeInTheDocument();
    expect(screen.queryByText('quiz.passed (100%)')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Начать тест' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Следующий урок' })).not.toBeInTheDocument();

    await act(async () => fireEvent.click(screen.getByText('Последний урок')));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/quizzes/by-lesson/lesson-3'),
      expect.any(Object),
    ));
    await act(async () => resolveSecondAttempts(jsonResponse([{ id: 'attempt-2', score_percent: 100, passed: true }])));
    expect(screen.queryByText('Новый тест')).not.toBeInTheDocument();
    expect(screen.queryByText('quiz.passed (100%)')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Начать тест' })).not.toBeInTheDocument();
  });

  it('does not inherit a passed attempt when the current lesson attempt read fails', async () => {
    const lessons = [lesson, { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 }];
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: lessons.map(({ id }) => id) });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_status: 'in_progress' }] });
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-1')) return jsonResponse({ id: 'quiz-1', title: 'Старый тест', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 });
      if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return jsonResponse([{ id: 'attempt-1', score_percent: 100, passed: true }]);
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-2')) return jsonResponse({ id: 'quiz-2', title: 'Новый тест', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 });
      if (url.endsWith('/v1/quizzes/quiz-2/attempts')) return jsonResponse({ detail: 'Attempts unavailable' }, 503);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'student-token', user: { user_id: 'student-1', role: 'student' } as never, initialized: true });

    render(<CoursePlayerPage />);
    expect(await screen.findByText('quiz.passed (100%)')).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getAllByText('Следующий урок')[0]));

    expect(await screen.findByText('Новый тест')).toBeInTheDocument();
    expect(screen.queryByText('quiz.passed (100%)')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Начать тест' })).toHaveAttribute(
      'href',
      '/courses/quiz/quiz-2?courseId=course-1&lessonId=lesson-2',
    );
    expect(screen.queryByRole('button', { name: 'Завершить курс' })).not.toBeInTheDocument();
  });

  it.each([
    {
      failure: 'HTTP 503',
      firstResponse: () => Promise.resolve(jsonResponse({ detail: 'Quiz unavailable' }, 503)),
      retryResponse: () => Promise.resolve(jsonResponse({ id: 'quiz-2', title: 'Новый тест', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 })),
      retryResult: 'quiz',
    },
    {
      failure: 'invalid JSON',
      firstResponse: () => Promise.resolve(new Response('{', { status: 200, headers: { 'Content-Type': 'application/json' } })),
      retryResponse: () => Promise.resolve(jsonResponse({ detail: 'No quiz' }, 404)),
      retryResult: 'none',
    },
    {
      failure: 'network error',
      firstResponse: () => Promise.reject(new Error('network unavailable')),
      retryResponse: () => Promise.resolve(jsonResponse({ id: 'quiz-2', title: 'Новый тест', pass_score: 80, time_limit: null, attempt_limit: 3, deferral_days: 0 })),
      retryResult: 'quiz',
    },
  ])('fails closed on quiz metadata $failure and retries to a confirmed result', async ({ firstResponse, retryResponse, retryResult }) => {
    const lessons = [lesson, { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 }];
    let secondLessonRequests = 0;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: lessons.map(({ id }) => id) });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_status: 'in_progress' }] });
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-1')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.endsWith('/v1/quizzes/by-lesson/lesson-2')) {
        secondLessonRequests += 1;
        return secondLessonRequests === 1 ? firstResponse() : retryResponse();
      }
      if (url.endsWith('/v1/quizzes/quiz-2/attempts')) return jsonResponse([]);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'student-token', user: { user_id: 'student-1', role: 'student' } as never, initialized: true });

    render(<CoursePlayerPage />);
    await screen.findByRole('button', { name: 'Следующий урок' });
    await act(async () => fireEvent.click(screen.getAllByText('Следующий урок')[0]));

    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить');
    expect(screen.queryByRole('link', { name: 'Начать тест' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Следующий урок' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Завершить курс' })).not.toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Повторить' })));

    if (retryResult === 'quiz') {
      expect(await screen.findByText('Новый тест')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Начать тест' })).toHaveAttribute(
        'href',
        '/courses/quiz/quiz-2?courseId=course-1&lessonId=lesson-2',
      );
      expect(screen.queryByRole('button', { name: 'Завершить курс' })).not.toBeInTheDocument();
    } else {
      expect(await screen.findByRole('button', { name: 'Завершить курс' })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Начать тест' })).not.toBeInTheDocument();
    }
    expect(secondLessonRequests).toBe(2);
  });

  it('keeps privileged preview progress local while following URL lesson changes and finishing', async () => {
    const lessons = [lesson, { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 }];
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse(course);
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: [] });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.includes('/v1/quizzes/by-lesson/')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      if (url.includes('/v1/progress/lessons/') || url.includes('/v1/courses/course-1/complete')) {
        throw new Error(`Unexpected preview mutation: ${url}`);
      }
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'methodologist-token', user: { id: 'methodologist-1', role: 'methodologist' } as never, initialized: true });

    const view = render(<CoursePlayerPage />);
    expect(await screen.findByRole('heading', { name: 'Шестой урок' })).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' })));
    expect(routerPush).toHaveBeenCalledWith('/courses/course-1?lessonId=lesson-2');

    searchParamsState.current = new URLSearchParams('lessonId=lesson-2');
    await act(async () => {
      view.rerender(<CoursePlayerPage />);
    });
    expect(await screen.findByRole('heading', { name: 'Следующий урок' })).toBeInTheDocument();
    expect(screen.getAllByText('Шестой урок')[0].parentElement?.querySelector('.bg-success')).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Завершить курс' })));
    expect(routerPush).toHaveBeenCalledWith('/courses');
    expect(toastSuccess).toHaveBeenCalledWith('Предпросмотр курса завершён');
    expect(fetchMock.mock.calls.some(([, request]) => request?.method === 'PUT' || request?.method === 'POST')).toBe(false);
  });

  it('isolates privileged preview progress by course and actor identity', async () => {
    const courseOneLessons = [lesson, { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 }];
    const courseTwoLesson = { ...lesson, id: 'course-two-lesson', title: 'Курс два', order_index: 0 };
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const currentCourse = courseRouteState.current;
      if (url.endsWith(`/v1/courses/${currentCourse}`)) return jsonResponse({ ...course, id: currentCourse });
      if (url.endsWith(`/v1/courses/${currentCourse}/structure`)) {
        return jsonResponse({ modules: [{ id: `module-${currentCourse}`, title: 'Модуль', description: '', order_index: 0, lessons: currentCourse === 'course-1' ? courseOneLessons : [courseTwoLesson] }] });
      }
      if (url.endsWith(`/v1/progress/courses/${currentCourse}/completed-ids`)) return jsonResponse({ completed_lesson_ids: [] });
      if (url.endsWith(`/v1/courses/${currentCourse}/access-window`)) return jsonResponse(null);
      if (url.includes('/v1/quizzes/by-lesson/')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'methodologist-token', user: { user_id: 'methodologist-1', role: 'methodologist' } as never, initialized: true });

    const view = render(<CoursePlayerPage />);
    expect(await screen.findByRole('heading', { name: 'Шестой урок' })).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' })));
    expect(screen.getAllByText('Шестой урок')[0].parentElement?.querySelector('.bg-success')).toBeInTheDocument();

    courseRouteState.current = 'course-2';
    searchParamsState.current = new URLSearchParams();
    await act(async () => view.rerender(<CoursePlayerPage />));
    expect(await screen.findByRole('heading', { name: 'Курс два' })).toBeInTheDocument();
    expect(screen.getAllByText('Курс два')[0].parentElement?.querySelector('.bg-success')).not.toBeInTheDocument();

    courseRouteState.current = 'course-1';
    useAuthStore.setState({ accessToken: 'methodologist-token-2', user: { user_id: 'methodologist-2', role: 'methodologist' } as never, initialized: true });
    await act(async () => view.rerender(<CoursePlayerPage />));
    expect(await screen.findByRole('heading', { name: 'Шестой урок' })).toBeInTheDocument();
    expect(screen.getAllByText('Шестой урок')[0].parentElement?.querySelector('.bg-success')).not.toBeInTheDocument();
  });

  it('ignores a delayed student progress response after entering preview mode', async () => {
    let resolveStudentProgress!: (value: Response) => void;
    let progressRequestCount = 0;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse(course);
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons: [lesson] }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) {
        progressRequestCount += 1;
        return progressRequestCount === 2
          ? new Promise((resolve) => { resolveStudentProgress = resolve; })
          : jsonResponse({ completed_lesson_ids: [] });
      }
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.includes('/v1/quizzes/by-lesson/')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.includes('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_status: 'in_progress' }] });
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'student-token', user: { user_id: 'student-1', role: 'student' } as never, initialized: true });
    const view = render(<CoursePlayerPage />);
    await screen.findByRole('heading', { name: 'Шестой урок' });

    searchParamsState.current = new URLSearchParams('lessonId=lesson-1');
    await act(async () => view.rerender(<CoursePlayerPage />));
    await waitFor(() => expect(progressRequestCount).toBe(2));
    useAuthStore.setState({ accessToken: 'methodologist-token', user: { user_id: 'methodologist-1', role: 'methodologist' } as never, initialized: true });
    await act(async () => view.rerender(<CoursePlayerPage />));
    await screen.findByRole('heading', { name: 'Шестой урок' });
    await waitFor(() => expect(progressRequestCount).toBe(3));
    await act(async () => resolveStudentProgress(jsonResponse({ completed_lesson_ids: ['lesson-1'] })));
    expect(screen.getAllByText('Шестой урок')[0].parentElement?.querySelector('.bg-success')).not.toBeInTheDocument();
  });

  it('ignores a delayed evidence response body after the learner identity changes', async () => {
    let resolveOldEvidence!: (value: Array<{ id: string }>) => void;
    let oldEvidenceBodyStarted = false;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const oldActor = (init?.headers as Record<string, string>)?.Authorization === 'Bearer student-old-token';
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse({ ...course, status: 'published' });
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons: [lesson] }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) return jsonResponse({ completed_lesson_ids: ['lesson-1'] });
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.endsWith('/v1/student/dashboard')) return jsonResponse({ enrolled_courses: [{ course_id: 'course-1', enrollment_id: oldActor ? 'enrollment-old' : 'enrollment-new', enrollment_status: 'completed' }] });
      if (url.includes('/v1/training-evidence/events/mine?')) {
        if (oldActor) return {
          ok: true,
          json: () => {
            oldEvidenceBodyStarted = true;
            return new Promise((resolve) => { resolveOldEvidence = resolve; });
          },
        } as Response;
        return jsonResponse([{ id: 'evidence-new' }]);
      }
      if (url.includes('/v1/quizzes/by-lesson/')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'student-old-token', user: { user_id: 'student-old', role: 'student' } as never, initialized: true });
    const view = render(<CoursePlayerPage />);
    await waitFor(() => expect(oldEvidenceBodyStarted).toBe(true));

    useAuthStore.setState({ accessToken: 'student-new-token', user: { user_id: 'student-new', role: 'student' } as never, initialized: true });
    await act(async () => view.rerender(<CoursePlayerPage />));
    expect(await screen.findByTestId('completion-evidence-event')).toHaveTextContent('evidence-new');
    await act(async () => resolveOldEvidence([{ id: 'evidence-old' }]));
    expect(screen.getByTestId('completion-evidence-event')).toHaveTextContent('evidence-new');
    expect(screen.queryByText('evidence-old')).not.toBeInTheDocument();
  });

  it('clears preview progress before a student progress read settles or fails', async () => {
    let rejectStudentProgress!: (reason?: unknown) => void;
    let progressRequestCount = 0;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/v1/courses/course-1')) return jsonResponse(course);
      if (url.endsWith('/v1/courses/course-1/structure')) return jsonResponse({ modules: [{ id: 'module-1', title: 'Модуль', description: '', order_index: 0, lessons: [lesson, { ...lesson, id: 'lesson-2', title: 'Следующий урок', order_index: 1 }] }] });
      if (url.endsWith('/v1/progress/courses/course-1/completed-ids')) {
        progressRequestCount += 1;
        return progressRequestCount === 1
          ? jsonResponse({ completed_lesson_ids: [] })
          : new Promise((_, reject) => { rejectStudentProgress = reject; });
      }
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(null);
      if (url.includes('/v1/quizzes/by-lesson/')) return jsonResponse({ detail: 'No quiz' }, 404);
      if (url.includes('/v1/learner/assistant/messages')) return jsonResponse([]);
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    useAuthStore.setState({ accessToken: 'methodologist-token', user: { user_id: 'methodologist-1', role: 'methodologist' } as never, initialized: true });
    const view = render(<CoursePlayerPage />);
    await screen.findByRole('heading', { name: 'Шестой урок' });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' })));
    expect(screen.getAllByText('Шестой урок')[0].parentElement?.querySelector('.bg-success')).toBeInTheDocument();

    await act(async () => {
      useAuthStore.setState({ accessToken: 'student-token', user: { user_id: 'student-1', role: 'student' } as never, initialized: true });
      view.rerender(<CoursePlayerPage />);
    });
    expect(screen.queryByRole('heading', { name: 'Шестой урок' })).not.toBeInTheDocument();
    await act(async () => rejectStudentProgress(new Error('progress unavailable')));
    expect(screen.queryByRole('heading', { name: 'Шестой урок' })).not.toBeInTheDocument();
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
      '## Заголовок урока\n\nБезопасный **жирный** текст\n<img src=x onerror="alert(1)"><script>alert(2)</script><a href="javascript:alert(3)">ссылка</a>',
    );
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', role: 'student' } as never,
      initialized: true,
    });

    render(<CoursePlayerPage />);

    expect(await screen.findByRole('heading', { level: 2, name: 'Заголовок урока' })).toBeInTheDocument();
    expect(screen.queryByText(/## Заголовок урока/)).not.toBeInTheDocument();
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
