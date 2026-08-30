import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));
const authMock = vi.hoisted(() => ({
  accessToken: 'test-token',
  initialize: vi.fn().mockResolvedValue(undefined),
}));
const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));
const editorAssistantMock = vi.hoisted(() => ({
  requestQuestionAssistantPreview: vi.fn(),
}));

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: typeof authMock) => unknown) => selector(authMock),
}));
vi.mock('@/lib/auth', () => ({ getAccessToken: () => 'test-token' }));
vi.mock('@/lib/api', () => ({ api: apiMock }));
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
vi.mock('@/lib/editorAssistant', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/editorAssistant')>();
  return { ...actual, ...editorAssistantMock };
});

import QuizzesAdminPage from '@/app/quizzes/page';

const ids = {
  question: '11111111-1111-1111-1111-111111111111', question2: '22222222-2222-2222-2222-222222222222',
  choice1: '33333333-3333-3333-3333-333333333333', choice2: '44444444-4444-4444-4444-444444444444', choice3: '55555555-5555-5555-5555-555555555555', choice4: '66666666-6666-6666-6666-666666666666',
  quiz: '77777777-7777-7777-7777-777777777777', lesson: '88888888-8888-8888-8888-888888888888', course: '99999999-9999-9999-9999-999999999999', module: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', request: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', preview: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
};

const initialQuestion = {
  id: ids.question,
  text: 'Старый вопрос',
  type: 'MCQ',
  points: 1,
  explanation: 'Старое пояснение',
  order_index: 0,
  choices: [
    { id: ids.choice1, text: 'Старый правильный ответ', is_correct: true, order_index: 0 },
    { id: ids.choice2, text: 'Старый неправильный ответ', is_correct: false, order_index: 1 },
  ],
};

const quiz = {
  id: ids.quiz,
  lesson_id: ids.lesson,
  title: 'Тест урока',
  pass_score: 80,
  time_limit: null,
  attempt_limit: 3,
  deferral_days: 0,
  questions: [initialQuestion],
};

const grouped = {
  courses: [{
    id: ids.course,
    title: 'Курс 1',
    status: 'draft',
    modules: [{
      id: ids.module,
      title: 'Модуль 1',
      order_index: 0,
      lessons: [{ id: ids.lesson, title: 'Урок 1', order_index: 0, quiz }],
    }],
  }],
  orphans: [],
};

function setupApi(updatedQuiz = quiz, groupedQuiz = quiz) {
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
  apiMock.get.mockResolvedValue({ data: groupedResponse });
  apiMock.post.mockResolvedValue({ data: updatedQuiz });
  apiMock.put.mockResolvedValue({ data: updatedQuiz });
}

async function selectQuiz() {
  const courseToggle = await screen.findByRole('button', { name: /Курс 1/ });
  if (courseToggle.getAttribute('aria-expanded') === 'false') {
    fireEvent.click(courseToggle);
  }
  await screen.findByText('Урок 1');
  fireEvent.click(screen.getByText('Урок 1'));
  await screen.findByRole('heading', { name: 'Тест урока' });
}

describe('quiz question editor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.accessToken = 'test-token';
    editorAssistantMock.requestQuestionAssistantPreview.mockResolvedValue({
      request_id: ids.request,
      preview_id: ids.preview,
      state: 'pending',
      applicability: 'not_applicable',
      base_snapshot_token: 'a'.repeat(64),
      operations: [],
      validation: null,
      source: { source_reference_count: 0, references: [] },
      provenance: null,
      failure: null,
    });
  });

  it('opens a create modal and POSTs the question with choices', async () => {
    const createdQuestion = {
      ...initialQuestion,
      id: ids.question2,
      text: 'Новый вопрос',
      choices: [
        { id: ids.choice3, text: 'Да', is_correct: true, order_index: 0 },
        { id: ids.choice4, text: 'Нет', is_correct: false, order_index: 1 },
      ],
    };
    setupApi({ ...quiz, questions: [createdQuestion] });
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
    expect(toastMock.success).toHaveBeenCalledWith('Вопрос добавлен');
    expect(apiMock.post).toHaveBeenCalledWith(`/v1/quizzes/${ids.quiz}/questions`, expect.objectContaining({
      text: 'Новый вопрос', type: 'MCQ', points: 2,
    }));
    expect(apiMock.post.mock.calls[0][1].choices).toEqual([
      { text: 'Да', is_correct: true, order_index: 0 },
      { text: 'Нет', is_correct: false, order_index: 1 },
    ]);
  });

  it('opens edit modal and PUTs choices while preserving existing choice ids', async () => {
    const updatedQuestion = {
      ...initialQuestion,
      text: 'Обновлённый вопрос',
      choices: [
        { id: ids.choice1, text: 'Обновлённый правильный ответ', is_correct: true, order_index: 0 },
        { id: ids.choice2, text: 'Обновлённый неправильный ответ', is_correct: false, order_index: 1 },
      ],
    };
    setupApi({ ...quiz, questions: [updatedQuestion] });
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
    expect(toastMock.success).toHaveBeenCalledWith('Вопрос обновлён');
    expect(apiMock.put).toHaveBeenCalledWith(`/v1/quizzes/${ids.quiz}/questions/${ids.question}`, expect.objectContaining({
      text: 'Обновлённый вопрос', type: 'MCQ', points: 1,
    }));
    expect(apiMock.put.mock.calls[0][1].choices).toEqual([
      { id: ids.choice1, text: 'Обновлённый правильный ответ', is_correct: true, order_index: 0 },
      { id: ids.choice2, text: 'Старый неправильный ответ', is_correct: false, order_index: 1 },
    ]);
  });

  it('blocks assistant preview while question edits are unsaved and enables it for the saved form', async () => {
    setupApi();
    render(<QuizzesAdminPage />);
    await selectQuiz();

    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    const questionInput = within(dialog).getByRole('textbox', { name: 'Текст вопроса' });
    const assistantButton = within(dialog).getByRole('button', { name: 'Сформировать предложение помощника' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Инструкция помощнику' }), {
      target: { value: 'Добавь больше информации' },
    });
    expect(assistantButton).not.toBeDisabled();
    fireEvent.change(questionInput, { target: { value: 'Мой несохранённый текст' } });
    expect(within(dialog).getByText('Сначала сохраните изменения вопроса, пояснения или вариантов ответа, затем сформируйте предложение.')).toBeInTheDocument();
    expect(assistantButton).toBeDisabled();
    expect(questionInput).toHaveValue('Мой несохранённый текст');
    expect(apiMock.put).not.toHaveBeenCalled();
    expect(editorAssistantMock.requestQuestionAssistantPreview).not.toHaveBeenCalled();
  });

  it.each([
    ['fewer than two choices', [{ ...initialQuestion.choices[0] }]],
    ['a choice without an id', [{ ...initialQuestion.choices[0], id: '' }, { ...initialQuestion.choices[1] }]],
    ['zero correct choices', initialQuestion.choices.map((choice) => ({ ...choice, is_correct: false }))],
    ['multiple correct choices', initialQuestion.choices.map((choice) => ({ ...choice, is_correct: true }))],
    ['duplicate choice ids', [{ ...initialQuestion.choices[0] }, { ...initialQuestion.choices[1], id: initialQuestion.choices[0].id }]],
  ])('does not expose the assistant for a saved MCQ with %s', async (_name, choices) => {
    const ineligibleQuestion = { ...initialQuestion, choices };
    const ineligibleQuiz = { ...quiz, questions: [ineligibleQuestion] };
    setupApi(ineligibleQuiz, ineligibleQuiz);
    render(<QuizzesAdminPage />);
    await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    expect(within(dialog).queryByRole('button', { name: 'Сформировать предложение помощника' })).not.toBeInTheDocument();
    expect(within(dialog).getByText('Помощник доступен для сохранённых вопросов с одним правильным ответом и стабильными вариантами ответа.')).toBeInTheDocument();
    expect(editorAssistantMock.requestQuestionAssistantPreview).not.toHaveBeenCalled();
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
    setupApi(multipleChoiceQuiz, multipleChoiceQuiz);
    render(<QuizzesAdminPage />);
    await selectQuiz();

    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    expect(within(dialog).getByRole('combobox', { name: 'Тип вопроса' })).toHaveValue(
      'multiple_choice'
    );
    expect(within(dialog).queryByRole('button', { name: 'Сформировать предложение помощника' })).not.toBeInTheDocument();
    expect(within(dialog).getByText('Помощник доступен для сохранённых вопросов с одним правильным ответом и стабильными вариантами ответа.')).toBeInTheDocument();

    const correctAnswerInputs = within(dialog).getAllByRole('checkbox');
    expect(correctAnswerInputs).toHaveLength(2);
    fireEvent.click(correctAnswerInputs[1]);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const body = apiMock.put.mock.calls[0][1];
    expect(body.type).toBe('multiple_choice');
    expect(body.choices.map((choice: { is_correct: boolean }) => choice.is_correct)).toEqual([
      true,
      true,
    ]);
  });

  it('starts course groups collapsed and exposes their state accessibly', async () => {
    setupApi();
    render(<QuizzesAdminPage />);

    const courseToggle = await screen.findByRole('button', { name: /Курс 1/ });
    expect(courseToggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Урок 1')).not.toBeInTheDocument();

    fireEvent.click(courseToggle);

    expect(courseToggle).toHaveAttribute('aria-expanded', 'true');
    const lessonButton = await screen.findByRole('button', { name: /Урок 1/ });
    expect(lessonButton).toBeInTheDocument();
    expect(lessonButton).toHaveAttribute('aria-pressed', 'false');
  });

  it('uses the same plain-language title as the navigation', async () => {
    setupApi();
    render(<QuizzesAdminPage />);

    expect(await screen.findByRole('heading', { name: 'Тесты и вопросы' })).toBeInTheDocument();
    expect(screen.queryByText('Конструктор тестов')).not.toBeInTheDocument();
  });

  it('names multiple-select questions by correct-answer semantics', async () => {
    const multipleChoiceQuiz = {
      ...quiz,
      questions: [{
        ...initialQuestion,
        type: 'multiple_choice',
        choices: initialQuestion.choices.map((choice) => ({ ...choice, is_correct: true })),
      }],
    };
    setupApi(multipleChoiceQuiz, multipleChoiceQuiz);
    render(<QuizzesAdminPage />);
    await selectQuiz();

    expect(screen.getByText('Несколько правильных ответов')).toBeInTheDocument();
    expect(screen.queryByText('Несколько вариантов')).not.toBeInTheDocument();
  });

  it('keeps the destructive action outside the colored settings control', async () => {
    setupApi();
    render(<QuizzesAdminPage />);
    await selectQuiz();

    const settingsButton = screen.getByRole('button', { name: 'Изменить параметры' });
    const deleteButton = screen.getByRole('button', { name: 'Удалить тест' });
    expect(settingsButton.className).toContain('bg-primary');
    expect(settingsButton.parentElement).not.toBe(deleteButton.parentElement);

    fireEvent.click(settingsButton);

    expect(screen.getByRole('button', { name: 'Удалить тест' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Изменить параметры' })).not.toBeInTheDocument();
  });
});
