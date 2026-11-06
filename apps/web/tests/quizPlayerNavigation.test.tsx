import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const routerPushMock = vi.hoisted(() => vi.fn());
const routerBackMock = vi.hoisted(() => vi.fn());
const routeState = vi.hoisted(() => ({ search: 'courseId=course-1&lessonId=lesson-1', quizId: 'quiz-1' }));

vi.mock('next/navigation', () => ({
  useParams: () => ({ quizId: routeState.quizId }),
  useSearchParams: () => new URLSearchParams(routeState.search),
  useRouter: () => ({ back: routerBackMock, push: routerPushMock, replace: vi.fn() }),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'courses.backToCourse': 'Вернуться к курсу',
      'common.back': 'Назад',
      'courses.nextLesson': 'Следующий урок',
      'quiz.assignmentTimeLeft': 'Оставшееся время на курс и тест',
      'completionUx.goToCompletion': 'Перейти к завершению курса',
    }[key] || key),
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  toast: { dismiss: vi.fn(), success: vi.fn(), error: vi.fn() },
}));
vi.mock('@/features/learner-workspace/LearnerEvidenceConfirmation', () => ({
  LearnerEvidenceConfirmation: ({ eventId, activityKind }: { eventId: string; activityKind: string }) => <div data-testid="quiz-evidence">{activityKind}:{eventId}</div>,
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
  time_limit: null as number | null,
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
let attemptsStatus = 200;
let quizExportResponse: Response | null = null;
let accessWindowPayload: unknown = null;
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
    routeState.search = 'courseId=course-1&lessonId=lesson-1';
    routeState.quizId = 'quiz-1';
    quizPayload = quiz;
    previousAttempts = [];
    attemptsStatus = 200;
    quizExportResponse = null;
    accessWindowPayload = null;
    structureLessons = [
      { id: 'lesson-1', title: 'Первый урок', order_index: 0 },
      { id: 'lesson-2', title: 'Следующий урок', order_index: 1 },
    ];
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { user_id: 'student-1', tenant_id: 'tenant-1', email: 'student@example.com', role: 'student' } as never,
      initialized: true,
    });
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/quizzes/quiz-1') && init?.method !== 'POST') return jsonResponse(quizPayload);
      if (url.endsWith('/v1/quizzes/quiz-1/attempts')) return jsonResponse(previousAttempts, attemptsStatus);
      if (url.endsWith('/v1/courses/course-1/structure')) {
        return jsonResponse({ modules: [{ lessons: structureLessons }] });
      }
      if (url.endsWith('/v1/courses/course-1/access-window')) return jsonResponse(accessWindowPayload);
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
      if (url.includes('/v1/training-evidence/quiz-attempts/mine/')) {
        return quizExportResponse ?? jsonResponse({ detail: 'Unexpected export request' }, 404);
      }
      return jsonResponse({ detail: 'Unexpected request' }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.useRealTimers());

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
    expect(screen.queryByTestId('quiz-evidence')).not.toBeInTheDocument();
    expect(screen.getByText('Тест пройден. Это не означает завершение всего курса.')).toBeInTheDocument();
  });

  it('downloads the immediate result as a validated PDF and revokes its object URL', async () => {
    const blob = new Blob(['%PDF-1.7\nresult'], { type: 'application/pdf' });
    quizExportResponse = { ok: true, blob: async () => blob } as unknown as Response;
    const createObjectURL = vi.fn(() => 'blob:quiz-result');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    await screen.findByText('Тест пройден');
    fireEvent.click(screen.getByRole('button', { name: 'Скачать результат теста' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'undefined/v1/training-evidence/quiz-attempts/mine/attempt-1/export',
      expect.objectContaining({ headers: { Authorization: 'Bearer student-token' } }),
    ));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledWith(blob));
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:quiz-result');
  });

  it('downloads an attempt from reloaded history and reports invalid PDF bytes', async () => {
    previousAttempts = [{ id: 'attempt-history', score_percent: 40, passed: false, started_at: '2026-10-18T00:00:00Z', completed_at: '2026-10-18T00:01:00Z' }];
    quizExportResponse = new Response('<html>not a pdf</html>', { status: 200, headers: { 'Content-Type': 'text/html' } });
    render(<QuizPlayerPage />);

    await screen.findByText('40%');
    fireEvent.click(screen.getByRole('button', { name: 'Скачать PDF' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Не удалось скачать результат теста'));
    expect(fetchMock).toHaveBeenCalledWith(
      'undefined/v1/training-evidence/quiz-attempts/mine/attempt-history/export',
      expect.anything(),
    );
  });

  it('reports the backend 409 for a historical attempt without a snapshot', async () => {
    previousAttempts = [{ id: 'attempt-legacy', score_percent: 100, passed: true, started_at: '2026-10-18T00:00:00Z', completed_at: '2026-10-18T00:01:00Z' }];
    quizExportResponse = jsonResponse({ detail: 'Historical attempt has no configured snapshot' }, 409);
    render(<QuizPlayerPage />);

    await screen.findByText('100%');
    fireEvent.click(screen.getByRole('button', { name: 'Скачать PDF' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Бланк для этой попытки недоступен'));
    expect(fetchMock).toHaveBeenCalledWith(
      'undefined/v1/training-evidence/quiz-attempts/mine/attempt-legacy/export',
      expect.anything(),
    );
  });

  it('treats a passed response as server-confirmed lesson completion', async () => {
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));

    await waitFor(() => expect(screen.getByRole('link', { name: 'Следующий урок' })).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/progress/lessons/lesson-1'),
      expect.anything(),
    );
  });

  it('does not spend a manual attempt while a question is unanswered', async () => {
    quizPayload = {
      ...quiz,
      questions: [quiz.questions[0], {
        ...quiz.questions[0], id: 'question-2', text: 'Второй вопрос?', order_index: 1,
        choices: [{ id: 'choice-2', text: 'Второй ответ', order_index: 0 }],
      }],
    };
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.next' }));
    await screen.findByText('Второй вопрос?');
    const finish = screen.getByRole('button', { name: 'quiz.finish' });
    expect(finish).toBeDisabled();
    fireEvent.click(finish);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/submit'))).toHaveLength(0);
    fireEvent.click(screen.getByRole('radio'));
    expect(finish).toBeEnabled();
    fireEvent.click(finish);
    await screen.findByText('Тест пройден');
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/submit'))).toHaveLength(1);
  });

  it('does not count a multi-select answer after its last choice is deselected', async () => {
    quizPayload = { ...quiz, questions: [{ ...quiz.questions[0], type: 'matching' }] };
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    const choice = screen.getByRole('checkbox');
    fireEvent.click(choice);
    expect(screen.getByRole('button', { name: 'quiz.finish' })).toBeEnabled();
    fireEvent.click(choice);
    expect(screen.getByText('0/1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'quiz.finish' })).toBeDisabled();
  });

  it('still submits unanswered questions automatically when a standalone timer expires', async () => {
    routeState.search = '';
    quizPayload = { ...quiz, time_limit: 1 / 60 };
    vi.useFakeTimers();
    await act(async () => { render(<QuizPlayerPage />); });
    expect(screen.getByRole('button', { name: 'quiz.finish' })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/submit'))).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/quizzes/quiz-1/submit'),
      expect.objectContaining({ body: expect.stringContaining('"selected_choice_ids":[]') }),
    );
    expect(screen.getByText('Тест пройден')).toBeInTheDocument();
  });

  it('uses the one assignment timer for the course and its quiz', async () => {
    quizPayload = { ...quiz, time_limit: 5 };
    accessWindowPayload = {
      server_now: '2026-09-16T10:00:00Z',
      access_policy: {
        completion_window_expires_at: '2026-09-16T10:10:00Z',
        due_at: null,
      },
    };

    render(<QuizPlayerPage />);

    const timer = await screen.findByRole('timer', { name: 'Оставшееся время на курс и тест' });
    expect(timer).toHaveTextContent('10:00');
    expect(screen.queryByRole('timer', { name: 'quiz.timeLeft' })).not.toBeInTheDocument();
  });

  it('keeps the learner SPA session when the final lesson is completed', async () => {
    structureLessons = [{ id: 'lesson-1', title: 'Первый урок', order_index: 0 }];
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));

    const finishButton = await screen.findByRole('button', { name: 'Перейти к завершению курса' });
    fireEvent.click(finishButton);

    expect(routerPushMock).toHaveBeenCalledWith('/courses/course-1?lessonId=lesson-1#finish-course');
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

  it('renders true/false as one-answer radios and submits only the selected choice', async () => {
    quizPayload = {
      ...quiz,
      questions: [{
        ...quiz.questions[0],
        type: 'true_false',
        choices: [
          { id: 'choice-true', text: 'true', order_index: 0 },
          { id: 'choice-false', text: 'false', order_index: 1 },
        ],
      }],
    };
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    expect(screen.getAllByRole('radio')).toHaveLength(2);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    fireEvent.click(screen.getAllByRole('radio')[0]);
    fireEvent.click(screen.getAllByRole('radio')[1]);
    expect(screen.getAllByRole('radio')[0]).not.toBeChecked();
    expect(screen.getAllByRole('radio')[1]).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));

    await screen.findByText('Тест пройден');
    const submitCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/submit'));
    expect(submitCall).toBeDefined();
    expect(JSON.parse(String((submitCall?.[1] as RequestInit).body)).answers[0].selected_choice_ids).toEqual(['choice-false']);
  });

  it('renders single-choice as one-answer radios and submits only the selected choice', async () => {
    quizPayload = {
      ...quiz,
      questions: [{
        ...quiz.questions[0],
        type: 'single_choice',
        choices: [
          { id: 'choice-one', text: 'Первый', order_index: 0 },
          { id: 'choice-two', text: 'Второй', order_index: 1 },
        ],
      }],
    };
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    expect(screen.getAllByRole('radio')).toHaveLength(2);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    fireEvent.click(screen.getAllByRole('radio')[0]);
    fireEvent.click(screen.getAllByRole('radio')[1]);
    expect(screen.getAllByRole('radio')[0]).not.toBeChecked();
    expect(screen.getAllByRole('radio')[1]).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));

    await screen.findByText('Тест пройден');
    const submitCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/submit'));
    expect(submitCall).toBeDefined();
    expect(JSON.parse(String((submitCall?.[1] as RequestInit).body)).answers[0].selected_choice_ids).toEqual(['choice-two']);
  });

  it('preserves persisted true/false choice text and identity when choices are reversed', async () => {
    quizPayload = {
      ...quiz,
      questions: [{
        ...quiz.questions[0],
        type: 'true_false',
        choices: [
          { id: 'choice-false', text: 'No', order_index: 0 },
          { id: 'choice-true', text: 'Yes', order_index: 1 },
        ],
      }],
    };
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    expect(screen.getByText('No')).toBeInTheDocument();
    expect(screen.getByText('Yes')).toBeInTheDocument();
    expect(screen.queryByText('quiz.true')).not.toBeInTheDocument();
    expect(screen.queryByText('quiz.false')).not.toBeInTheDocument();
  });

  it.each(['multiple_choice', 'unknown_choice'])('preserves multi-select behavior for %s without guessing its meaning', async (type) => {
    quizPayload = { ...quiz, questions: [{ ...quiz.questions[0], type, choices: [
      { id: 'choice-one', text: 'Первый', order_index: 0 },
      { id: 'choice-two', text: 'Второй', order_index: 1 },
    ] }] };
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    await screen.findByText('Тест пройден');
    const submitCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/submit'));
    expect(JSON.parse(String((submitCall?.[1] as RequestInit).body)).answers[0].selected_choice_ids).toEqual(['choice-one', 'choice-two']);
  });

  it('blocks answer selection and submission when all attempts were already used', async () => {
    previousAttempts = Array.from({ length: quiz.attempt_limit }, (_, index) => ({
      id: `attempt-${index}`,
      score_percent: 0,
      passed: false,
      started_at: '2026-09-30T00:00:00Z',
      completed_at: '2026-09-30T00:01:00Z',
    }));
    render(<QuizPlayerPage />);

    await screen.findByText('Верный ответ?');
    expect(screen.getByRole('alert')).toHaveTextContent('quiz.attemptLimit');
    const answer = screen.getByRole('radio');
    expect(answer).toBeDisabled();
    fireEvent.click(answer);
    const finish = screen.getByRole('button', { name: 'quiz.finish' });
    expect(finish).toBeDisabled();
    fireEvent.click(finish);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/submit'))).toHaveLength(0);
    expect(screen.getByRole('link', { name: 'Вернуться к курсу' })).toHaveAttribute(
      'href', '/courses/course-1?lessonId=lesson-1',
    );
  });

  it('uses a generic back action when opened without a course context', async () => {
    routeState.search = '';
    previousAttempts = Array.from({ length: quiz.attempt_limit }, (_, index) => ({
      id: `attempt-${index}`,
      score_percent: 0,
      passed: false,
      started_at: '2026-09-30T00:00:00Z',
      completed_at: '2026-09-30T00:01:00Z',
    }));
    render(<QuizPlayerPage />);

    const back = await screen.findByRole('button', { name: 'Назад' });
    expect(screen.queryByRole('link', { name: 'Вернуться к курсу' })).not.toBeInTheDocument();
    fireEvent.click(back);
    expect(routerBackMock).toHaveBeenCalledTimes(1);
  });

  it('fails closed when attempt history cannot be read', async () => {
    attemptsStatus = 503;
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    expect(screen.getByRole('alert')).toHaveTextContent('quiz.attemptHistoryUnavailable');
    expect(screen.getByRole('radio')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'quiz.finish' })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/submit'))).toHaveLength(0);
  });

  it('preserves a failed final result without offering another attempt', async () => {
    previousAttempts = Array.from({ length: quiz.attempt_limit - 1 }, (_, index) => ({
      id: `attempt-${index}`, score_percent: 0, passed: false,
      started_at: '', completed_at: '',
    }));
    const defaultFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/submit')) {
        previousAttempts = [...previousAttempts, { id: 'last', score_percent: 0, passed: false, started_at: '', completed_at: '' }];
        return jsonResponse({ attempt: { score_percent: 0 }, passed: false, message: 'Последняя попытка не пройдена' });
      }
      return defaultFetch(input, init);
    });
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    expect(screen.getByRole('radio')).toBeEnabled();
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    await screen.findByText('Последняя попытка не пройдена');
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/attempts'))).toHaveLength(2));
    expect(screen.queryByRole('button', { name: 'quiz.tryAgain' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Вернуться к курсу' })).toBeInTheDocument();
    expect(screen.getByText('Попытки исчерпаны. Обратитесь к методисту, чтобы уточнить дальнейшие действия.')).toBeInTheDocument();
  });

  it('does not offer retry when refreshing history after submission fails', async () => {
    const defaultFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/submit')) {
        attemptsStatus = 503;
        return jsonResponse({ attempt: { score_percent: 0 }, passed: false, message: 'Попытка не пройдена' });
      }
      return defaultFetch(input, init);
    });
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    await screen.findByText('Попытка не пройдена');
    expect(screen.queryByRole('button', { name: 'quiz.tryAgain' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Вернуться к курсу' })).toBeInTheDocument();
    attemptsStatus = 200;
    previousAttempts = [{ id: 'attempt-1', score_percent: 0, passed: false, started_at: '', completed_at: '' }];
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(screen.getByText('Попытка не пройдена')).toBeInTheDocument();
    expect(await screen.findByText('Осталось попыток: 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'quiz.tryAgain' })).toBeEnabled();
  });

  it('shows only the aggregate result and passes the real submitted event identity to confirmation', async () => {
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith('/submit')
      ? Promise.resolve(jsonResponse({ attempt: { id: 'attempt-1', score_percent: 100 }, passed: true, message: 'Тест пройден', training_evidence_event_id: 'event-quiz-1', correct_answers: [{ answer: 'SECRET KEY' }], explanation: 'INVENTED TOPIC ADVICE' }))
      : original(input, init));
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    expect(await screen.findByTestId('quiz-evidence')).toHaveTextContent('quiz:event-quiz-1');
    expect(screen.queryByText('Верный ответ?')).not.toBeInTheDocument();
    expect(screen.queryByText('SECRET KEY')).not.toBeInTheDocument();
    expect(screen.queryByText('INVENTED TOPIC ADVICE')).not.toBeInTheDocument();
  });

  it('ignores a delayed submission after the learner actor changes', async () => {
    let resolve!: (value: Response) => void;
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith('/submit')
      ? new Promise<Response>((done) => { resolve = done; }) : original(input, init));
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    act(() => useAuthStore.setState({ accessToken: 'new-student-token', user: { user_id: 'student-2', tenant_id: 'tenant-1', role: 'student' } as never }));
    await screen.findByText('Верный ответ?');
    await act(async () => { resolve(jsonResponse({ attempt: { score_percent: 100 }, passed: true, message: 'OLD RESULT', training_evidence_event_id: 'old-event' })); });
    expect(screen.queryByText('OLD RESULT')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quiz-evidence')).not.toBeInTheDocument();
    expect(screen.getByRole('radio')).not.toBeChecked();
  });

  it('ignores a delayed submission after same-user explicit session replacement', async () => {
    let resolve!: (value: Response) => void;
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith('/submit')
      ? new Promise<Response>((done) => { resolve = done; }) : original(input, init));
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    act(() => useAuthStore.setState((state) => ({ sessionEpoch: state.sessionEpoch + 1 })));
    await screen.findByText('Верный ответ?');
    await act(async () => { resolve(jsonResponse({ attempt: { score_percent: 100 }, passed: true, message: 'OLD RESULT', training_evidence_event_id: 'old-event' })); });
    expect(screen.queryByText('OLD RESULT')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quiz-evidence')).not.toBeInTheDocument();
    expect(screen.getByRole('radio')).not.toBeChecked();
  });

  it('clears selected answers on same-user explicit session replacement', async () => {
    routeState.search = '';
    render(<QuizPlayerPage />);
    fireEvent.click(await screen.findByRole('radio'));
    expect(screen.getByRole('radio')).toBeChecked();
    await act(async () => { useAuthStore.setState((state) => ({ sessionEpoch: state.sessionEpoch + 1 })); });
    expect(await screen.findByRole('radio')).not.toBeChecked();
  });

  it('preserves selected answers and the running standalone timer on token-only rotation', async () => {
    routeState.search = '';
    quizPayload = { ...quiz, time_limit: 1 };
    vi.useFakeTimers();
    await act(async () => { render(<QuizPlayerPage />); });
    fireEvent.click(screen.getByRole('radio'));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByRole('timer')).toHaveTextContent('0:55');
    const callsBeforeRotation = fetchMock.mock.calls.length;
    await act(async () => { useAuthStore.setState({ accessToken: 'refreshed-student-token' }); });
    expect(screen.getByRole('radio')).toBeChecked();
    expect(screen.getByRole('timer')).toHaveTextContent('0:55');
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforeRotation);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByRole('timer')).toHaveTextContent('0:54');
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    await act(async () => undefined);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/submit'), expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer refreshed-student-token' }) }));
  });

  it('preserves the confirmed result and its exact evidence identity on token-only rotation', async () => {
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith('/submit')
      ? Promise.resolve(jsonResponse({ attempt: { id: 'attempt-1', score_percent: 100 }, passed: true, message: 'Тест пройден', training_evidence_event_id: 'event-quiz-1' }))
      : original(input, init));
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    await screen.findByTestId('quiz-evidence');
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/attempts'))).toHaveLength(2));
    const callsBeforeRotation = fetchMock.mock.calls.length;
    act(() => useAuthStore.setState({ accessToken: 'refreshed-student-token' }));
    expect(screen.getByText('Тест пройден')).toBeInTheDocument();
    expect(screen.getByTestId('quiz-evidence')).toHaveTextContent('quiz:event-quiz-1');
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforeRotation);
  });

  it('accepts the in-flight result for the same learner after a credential refresh', async () => {
    let resolve!: (value: Response) => void;
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith('/submit')
      ? new Promise<Response>((done) => { resolve = done; }) : original(input, init));
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    act(() => useAuthStore.setState({ accessToken: 'refreshed-student-token' }));
    await act(async () => { resolve(jsonResponse({ attempt: { id: 'attempt-1', score_percent: 100 }, passed: true, message: 'Тест пройден', training_evidence_event_id: 'event-quiz-1' })); });
    expect(screen.getByTestId('quiz-evidence')).toHaveTextContent('quiz:event-quiz-1');
    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining('/attempts'), expect.objectContaining({ headers: { Authorization: 'Bearer refreshed-student-token' } }));
  });

  it.each(['actor', 'tenant', 'role', 'course', 'lesson', 'quiz'])('clears existing answers on a %s identity change, not just token changes', async (change) => {
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith('/v1/quizzes/quiz-2')
      ? Promise.resolve(jsonResponse({ ...quiz, id: 'quiz-2' })) : original(input, init));
    const view = render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    expect(screen.getByRole('radio')).toBeChecked();
    if (change === 'actor' || change === 'tenant' || change === 'role') {
      act(() => useAuthStore.setState({ user: {
        user_id: change === 'actor' ? 'student-2' : 'student-1',
        tenant_id: change === 'tenant' ? 'tenant-2' : 'tenant-1',
        role: change === 'role' ? 'methodologist' : 'student',
      } as never }));
    } else {
      if (change === 'quiz') routeState.quizId = 'quiz-2';
      else routeState.search = change === 'course' ? 'courseId=course-2&lessonId=lesson-1' : 'courseId=course-1&lessonId=lesson-2';
      view.rerender(<QuizPlayerPage />);
    }
    expect(await screen.findByRole('radio')).not.toBeChecked();
    expect(screen.queryByTestId('quiz-evidence')).not.toBeInTheDocument();
  });

  it('clears the old attempt and rejects late result-history callbacks when the server assignment occurrence changes', async () => {
    accessWindowPayload = { server_now: '2026-11-01T10:00:00Z', access_policy: { enrollment_id: 'assignment-1', due_at: null, completion_window_expires_at: null } };
    let resolveOldHistory!: (value: Response) => void;
    let historyReads = 0;
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/submit')) return Promise.resolve(jsonResponse({ attempt: { id: 'attempt-1', score_percent: 0 }, passed: false, message: 'OLD ASSIGNMENT RESULT', training_evidence_event_id: 'old-event' }));
      if (String(input).endsWith('/attempts') && ++historyReads === 2) return new Promise<Response>((done) => { resolveOldHistory = done; });
      return original(input, init);
    });
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.finish' }));
    await screen.findByText('OLD ASSIGNMENT RESULT');
    accessWindowPayload = { server_now: '2026-11-01T10:00:00Z', access_policy: { enrollment_id: 'assignment-2', due_at: null, completion_window_expires_at: null } };
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(await screen.findByRole('radio')).not.toBeChecked();
    expect(screen.queryByText('OLD ASSIGNMENT RESULT')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quiz-evidence')).not.toBeInTheDocument();
    await act(async () => { resolveOldHistory(jsonResponse(Array.from({ length: 3 }, (_, index) => ({ id: `old-${index}`, score_percent: 0, passed: false })))); });
    expect(screen.getByRole('radio')).toBeEnabled();
    expect(screen.queryByText('quiz.attemptLimit')).not.toBeInTheDocument();
  });

  it('does not allow privileged actors to submit learner attempts', async () => {
    useAuthStore.setState({ user: { user_id: 'methodologist-1', role: 'methodologist' } as never });
    render(<QuizPlayerPage />);
    await screen.findByText('Верный ответ?');
    expect(screen.getByRole('radio')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'quiz.finish' })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/submit'))).toBe(false);
  });

});
