import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const authMock = vi.hoisted(() => ({
  accessToken: 'test-token',
  initialize: vi.fn().mockResolvedValue(undefined),
}));
const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: typeof authMock) => unknown) => selector(authMock),
}));
vi.mock('@/lib/auth', () => ({ getAccessToken: () => 'test-token' }));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'common.cancel': 'Отмена',
      'common.create': 'Создать',
      'common.delete': 'Удалить',
      'common.edit': 'Редактировать',
      'common.save': 'Сохранить',
      'common.saving': 'Сохраняем',
      'quiz.points': 'баллов',
      'quiz.title': 'Тест',
    }[key] ?? key),
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));
vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(false), dialog: null }),
}));
vi.mock('@/components/ui/Toast', () => ({ toast: toastMock }));

import QuizzesAdminPage from '@/app/quizzes/page';

const initialQuestion = {
  id: 'question-1',
  text: 'Старый вопрос',
  type: 'MCQ',
  points: 1,
  explanation: 'Старое пояснение',
  order_index: 0,
  choices: [
    { id: 'choice-1', text: 'Старый правильный ответ', is_correct: true, order_index: 0 },
    { id: 'choice-2', text: 'Старый неправильный ответ', is_correct: false, order_index: 1 },
  ],
};

const quiz = {
  id: 'quiz-1',
  lesson_id: 'lesson-1',
  title: 'Тест урока',
  pass_score: 80,
  time_limit: null,
  attempt_limit: 3,
  deferral_days: 0,
  questions: [initialQuestion],
};

const grouped = {
  courses: [{
    id: 'course-1',
    title: 'Курс 1',
    status: 'draft',
    modules: [{
      id: 'module-1',
      title: 'Модуль 1',
      order_index: 0,
      lessons: [{ id: 'lesson-1', title: 'Урок 1', order_index: 0, quiz }],
    }],
  }],
  orphans: [],
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function setupFetch(updatedQuiz = quiz, groupedQuiz = quiz) {
  const groupedResponse = {
    ...grouped,
    courses: grouped.courses.map((course) => ({
      ...course,
      modules: course.modules.map((module) => ({
        ...module,
        lessons: module.lessons.map((lesson) => ({ ...lesson, quiz: groupedQuiz })),
      })),
    })),
  };
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/v1/quizzes/grouped')) return jsonResponse(groupedResponse);
    if (init?.method === 'POST' && url.endsWith('/v1/quizzes/quiz-1/questions')) {
      return jsonResponse(updatedQuiz);
    }
    if (init?.method === 'PUT' && url.endsWith('/v1/quizzes/quiz-1/questions/question-1')) {
      return jsonResponse(updatedQuiz);
    }
    return jsonResponse({ detail: 'Unexpected request' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
}

async function selectQuiz() {
  await screen.findByText('Урок 1');
  fireEvent.click(screen.getByText('Урок 1'));
  await screen.findByRole('heading', { name: 'Тест урока' });
}

describe('quiz question editor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.accessToken = 'test-token';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('opens a create modal and POSTs the question with choices', async () => {
    const createdQuestion = {
      ...initialQuestion,
      id: 'question-2',
      text: 'Новый вопрос',
      choices: [
        { id: 'choice-3', text: 'Да', is_correct: true, order_index: 0 },
        { id: 'choice-4', text: 'Нет', is_correct: false, order_index: 1 },
      ],
    };
    setupFetch({ ...quiz, questions: [createdQuestion] });
    render(<QuizzesAdminPage />);
    await selectQuiz();

    fireEvent.click(screen.getByRole('button', { name: 'Создать вопрос' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый вопрос' });
    expect(dialog.className).toContain('max-w-4xl');
    expect(dialog.className).toContain('overflow-y-auto');

    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), {
      target: { value: 'Новый вопрос' },
    });
    fireEvent.change(within(dialog).getByRole('spinbutton', { name: 'Баллы за правильный ответ' }), {
      target: { value: '2' },
    });
    fireEvent.change(within(dialog).getByPlaceholderText('Вариант 1…'), {
      target: { value: 'Да' },
    });
    fireEvent.change(within(dialog).getByPlaceholderText('Вариант 2…'), {
      target: { value: 'Нет' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Создать вопрос' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(postCall).toBeDefined();
    const body = JSON.parse((postCall?.[1] as RequestInit).body as string);
    expect(body).toMatchObject({ text: 'Новый вопрос', type: 'MCQ', points: 2 });
    expect(body.choices).toEqual([
      { text: 'Да', is_correct: true, order_index: 0 },
      { text: 'Нет', is_correct: false, order_index: 1 },
    ]);
  });

  it('opens edit modal and PUTs choices while preserving existing choice ids', async () => {
    const updatedQuestion = {
      ...initialQuestion,
      text: 'Обновлённый вопрос',
      choices: [
        { id: 'choice-1', text: 'Обновлённый правильный ответ', is_correct: true, order_index: 0 },
        { id: 'choice-2', text: 'Обновлённый неправильный ответ', is_correct: false, order_index: 1 },
      ],
    };
    setupFetch({ ...quiz, questions: [updatedQuestion] });
    render(<QuizzesAdminPage />);
    await selectQuiz();

    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    expect(within(dialog).getByDisplayValue('Старый вопрос')).toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), {
      target: { value: 'Обновлённый вопрос' },
    });
    fireEvent.change(within(dialog).getByDisplayValue('Старый правильный ответ'), {
      target: { value: 'Обновлённый правильный ответ' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
    expect(putCall).toBeDefined();
    const body = JSON.parse((putCall?.[1] as RequestInit).body as string);
    expect(body).toMatchObject({ text: 'Обновлённый вопрос', type: 'MCQ', points: 1 });
    expect(body.choices).toEqual([
      { id: 'choice-1', text: 'Обновлённый правильный ответ', is_correct: true, order_index: 0 },
      { id: 'choice-2', text: 'Старый неправильный ответ', is_correct: false, order_index: 1 },
    ]);
  });

  it('preserves multiple-choice semantics and allows several correct answers', async () => {
    const multipleChoiceQuestion = {
      ...initialQuestion,
      type: 'multiple_choice',
    };
    const multipleChoiceQuiz = {
      ...quiz,
      questions: [multipleChoiceQuestion],
    };
    setupFetch(multipleChoiceQuiz, multipleChoiceQuiz);
    render(<QuizzesAdminPage />);
    await selectQuiz();

    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    expect(within(dialog).getByRole('combobox', { name: 'Тип вопроса' })).toHaveValue(
      'multiple_choice'
    );

    const correctAnswerInputs = within(dialog).getAllByRole('checkbox');
    expect(correctAnswerInputs).toHaveLength(2);
    fireEvent.click(correctAnswerInputs[1]);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
    const body = JSON.parse((putCall?.[1] as RequestInit).body as string);
    expect(body.type).toBe('multiple_choice');
    expect(body.choices.map((choice: { is_correct: boolean }) => choice.is_correct)).toEqual([
      true,
      true,
    ]);
  });
});
