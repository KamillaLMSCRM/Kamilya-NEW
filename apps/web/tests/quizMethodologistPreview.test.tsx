import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const replaceMock = vi.hoisted(() => vi.fn());
const translateMock = vi.hoisted(() => (key: string, params?: Record<string, string | number>) => {
  if (key === 'quiz.questionNumber') return `Вопрос ${params?.current} из ${params?.total}`;
  if (key === 'quiz.previewScore') return `${params?.score}% · ${params?.earned} из ${params?.total} баллов`;
  return ({
    'quiz.previewTitle': 'Предпросмотр теста методистом',
    'quiz.previewNotice': 'Результат не сохраняется.',
    'quiz.previewFinish': 'Проверить ответы без сохранения',
    'quiz.previewPassed': 'Предпросмотр пройден',
    'quiz.previewFailed': 'Предпросмотр не пройден',
    'quiz.selectedAnswer': 'Выбрано',
    'quiz.correctAnswer': 'Правильный ответ',
    'quiz.answerCorrect': 'Верно',
    'quiz.answerIncorrect': 'Неверно',
    'quiz.previewRetry': 'Ответить заново',
    'quiz.previewAccessDeniedTitle': 'Предпросмотр недоступен',
    'quiz.previewAccessDenied': 'Только методисту.',
    'courses.backToCourse': 'Вернуться к курсу',
    'nav.dashboard': 'Главная',
  } as Record<string, string>)[key] || key;
});

vi.mock('next/navigation', () => ({
  useParams: () => ({ quizId: 'quiz-1' }),
  useSearchParams: () => new URLSearchParams('courseId=course-1&lessonId=lesson-1'),
  useRouter: () => ({ replace: replaceMock }),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: translateMock }),
}));

vi.mock('@/components/ui/Toast', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import QuizMethodologistPreviewPage from '@/app/courses/quiz/[quizId]/preview/page';
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
  questions: [{
    id: 'question-1',
    text: 'Как следует поступить?',
    type: 'MCQ',
    points: 1,
    explanation: 'Используйте защищённый канал.',
    order_index: 0,
    choices: [
      { id: 'choice-wrong', text: 'Отправить в открытый чат', order_index: 0 },
      { id: 'choice-correct', text: 'Использовать защищённый канал', order_index: 1 },
    ],
  }],
};

describe('methodologist quiz preview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      accessToken: 'methodologist-token',
      user: { id: 'methodologist-1', email: 'methodologist@example.com', role: 'methodologist' } as never,
      initialized: true,
    });
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/v1/quizzes/quiz-1') && init?.method !== 'POST') return jsonResponse(quiz);
      if (url.endsWith('/v1/quizzes/quiz-1/preview-submit')) {
        return jsonResponse({
          quiz_id: 'quiz-1',
          score_percent: 0,
          total_points: 1,
          earned_points: 0,
          passed: false,
          graded_answers: [{
            question_id: 'question-1',
            selected_choice_ids: ['choice-wrong'],
            correct_choice_ids: ['choice-correct'],
            is_correct: false,
            points_earned: 0,
            points_possible: 1,
          }],
        });
      }
      return jsonResponse({ detail: `Unexpected request: ${url}` }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('shows selected and correct answers without creating learner state', async () => {
    render(<QuizMethodologistPreviewPage />);

    await screen.findByText('Как следует поступить?');
    fireEvent.click(screen.getByRole('radio', { name: /Отправить в открытый чат/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Проверить ответы без сохранения' }));

    await screen.findByText('Предпросмотр не пройден');
    expect(screen.getByText('Выбрано')).toBeInTheDocument();
    expect(screen.getByText('Правильный ответ')).toBeInTheDocument();
    expect(screen.getByText('Используйте защищённый канал.')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/quizzes/quiz-1/preview-submit'),
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/attempts'),
      expect.anything(),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/quizzes\/quiz-1\/submit$/),
      expect.anything(),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Ответить заново' }));
    expect(screen.queryByText('Правильный ответ')).not.toBeInTheDocument();
  });

  it('keeps persisted true/false labels and single-choice semantics in preview', async () => {
    const previewQuiz = {
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
    fetchMock.mockImplementationOnce(async () => jsonResponse(previewQuiz));
    render(<QuizMethodologistPreviewPage />);

    await screen.findByText('Как следует поступить?');
    expect(screen.getByText('No')).toBeInTheDocument();
    expect(screen.getByText('Yes')).toBeInTheDocument();
    expect(screen.getAllByRole('radio')).toHaveLength(2);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });

  it('submits one choice for single-choice preview questions', async () => {
    const previewQuiz = {
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
    fetchMock.mockImplementationOnce(async () => jsonResponse(previewQuiz));
    render(<QuizMethodologistPreviewPage />);

    await screen.findByText('Как следует поступить?');
    expect(screen.getAllByRole('radio')).toHaveLength(2);
    fireEvent.click(screen.getAllByRole('radio')[0]);
    fireEvent.click(screen.getAllByRole('radio')[1]);
    fireEvent.click(screen.getByRole('button', { name: 'Проверить ответы без сохранения' }));

    await screen.findByText('Предпросмотр не пройден');
    const submitCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/preview-submit'));
    expect(submitCall).toBeDefined();
    expect(JSON.parse(String((submitCall?.[1] as RequestInit).body)).answers[0].selected_choice_ids).toEqual(['choice-two']);
  });

  it('blocks the separate route for learner roles before any quiz request', async () => {
    useAuthStore.setState({
      accessToken: 'student-token',
      user: { id: 'student-1', email: 'student@example.com', role: 'student' } as never,
      initialized: true,
    });

    render(<QuizMethodologistPreviewPage />);

    expect(await screen.findByText('Предпросмотр недоступен')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Главная' }));
    await waitFor(() => expect(replaceMock).toHaveBeenCalled());
  });
});
