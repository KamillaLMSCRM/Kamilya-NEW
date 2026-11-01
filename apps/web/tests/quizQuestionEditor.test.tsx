import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));
const authMock = vi.hoisted(() => ({
  accessToken: 'test-token',
  sessionEpoch: 1,
  user: null as { user_id: string; tenant_id: string; role: string } | null,
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
  useAuthStore: Object.assign((selector: (state: typeof authMock) => unknown) => selector(authMock), { getState: () => authMock }),
}));
vi.mock('@/lib/auth', () => ({ getAccessToken: () => 'test-token' }));
vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string, params?: Record<string, unknown>) => ({
      'common.cancel': 'Отмена',
      'common.create': 'Создать',
      'common.delete': 'Удалить',
      'common.edit': 'Редактировать',
      'common.save': 'Сохранить',
      'common.saving': 'Сохраняем',
      'quiz.points': 'баллов',
      'quiz.title': 'Тест',
      'authenticatedUi.quizUi.title': 'Тесты и вопросы',
      'authenticatedUi.quizUi.description': 'Создание и редактирование тестов. Выберите урок, добавьте вопросы вручную или сгенерируйте черновик из контента урока с помощью AI.',
      'authenticatedUi.quizUi.tests': 'Тесты',
      'authenticatedUi.quizUi.settings': 'Параметры теста',
      'authenticatedUi.quizUi.editSettings': 'Изменить параметры',
      'authenticatedUi.quizUi.deleteTitle': 'Удаление теста',
      'authenticatedUi.quizUi.deleteDescription': 'Удалит тест и все его вопросы без возможности восстановления.',
      'authenticatedUi.quizUi.deleteTest': 'Удалить тест',
      'authenticatedUi.quizUi.questions': 'Вопросы',
      'authenticatedUi.quizUi.question': 'вопрос',
      'authenticatedUi.quizUi.mcq': 'Один правильный ответ',
      'authenticatedUi.quizUi.multiple': 'Несколько правильных ответов',
      'authenticatedUi.quizUi.trueFalse': 'Верно / неверно',
      'authenticatedUi.quizUi.matching': 'Сопоставление',
      'authenticatedUi.quizUi.editQuestion': 'Редактирование вопроса',
      'authenticatedUi.quizUi.newQuestion': 'Новый вопрос',
      'authenticatedUi.quizUi.questionDescription': 'Сформулируйте вопрос, настройте баллы и отметьте правильные ответы.',
      'authenticatedUi.quizUi.questionText': 'Текст вопроса',
      'authenticatedUi.quizUi.questionType': 'Тип вопроса',
      'authenticatedUi.quizUi.singleOption': 'Один правильный вариант',
      'authenticatedUi.quizUi.multipleOptions': 'Несколько правильных вариантов',
      'authenticatedUi.quizUi.matchingUnavailable': 'Сопоставление (редактор пока недоступен)',
      'authenticatedUi.quizUi.points': 'Баллы за правильный ответ',
      'authenticatedUi.quizUi.explanation': 'Пояснение после ответа',
      'authenticatedUi.quizUi.answerChoices': 'Варианты ответа',
      'authenticatedUi.quizUi.selectAll': 'Отметьте все правильные варианты.',
      'authenticatedUi.quizUi.selectOne': 'Отметьте один правильный вариант.',
      'authenticatedUi.quizUi.addChoice': 'Добавить вариант',
      'authenticatedUi.quizUi.choicePlaceholder': `Вариант ${String(params?.index ?? '')}…`,
      'authenticatedUi.quizUi.questionAdded': 'Вопрос добавлен',
      'authenticatedUi.quizUi.questionUpdated': 'Вопрос обновлён',
      'authenticatedUi.quizUi.assistantDisabled': 'Сначала сохраните изменения вопроса, пояснения или вариантов ответа, затем сформируйте предложение.',
      'authenticatedUi.quizUi.assistantAvailable': 'Помощник доступен для сохранённых вопросов с одним правильным ответом и стабильными вариантами ответа.',
      'authenticatedUi.quizUi.course': 'Курс',
      'authenticatedUi.quizUi.module': 'Модуль',
      'authenticatedUi.quizUi.lesson': 'Урок',
      'authenticatedUi.quizUi.minutesShort': 'мин',
      'authenticatedUi.quizUi.guidancePlaceholder': 'Например: добавьте больше практических ситуаций',
      'authenticatedUi.quizUi.secondsShort': `${String(params?.seconds ?? '')} с`,
      'authenticatedUi.quizUi.generatedIn': `сгенерировано за ${String(params?.seconds ?? '')} с`,
      'authenticatedUi.quizUi.reviewWarning': 'Проверьте вопросы и ответы перед сохранением.',
      'authenticatedUi.quizUi.timeLimitHint': 'Оставьте пустым, чтобы не ограничивать время',
      'authenticatedUi.quizUi.loadOrCreate': 'Загрузите существующий тест или создайте новый',
      'authenticatedUi.quizUi.questionPlaceholder': 'Введите текст вопроса…',
      'authenticatedUi.quizUi.explanationPlaceholder': 'Пояснение, которое обучающийся увидит после ответа…',
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
import { clearQuestionDraft, readQuestionDraft } from '@/features/quiz-authoring/questionDraft';
import { currentAuthorSession } from '@/features/course-authoring/authorSession';

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
  time_limit: null as number | null,
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
  it('preserves a dirty question and volatile recovery through same-actor token rotation', async () => {
    setupApi(); const view = render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Keep dirty question on refresh' } });
    authMock.accessToken = 'rotated-token'; view.rerender(<QuizzesAdminPage />);
    expect(screen.getByDisplayValue('Keep dirty question on refresh')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Есть несохранённые изменения вопроса');
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    const scope = currentAuthorSession(authMock);
    expect(scope).not.toHaveProperty('token');
    expect(JSON.stringify(scope)).not.toContain('rotated-token');
    expect(readQuestionDraft(scope)?.question.text).toBe('Keep dirty question on refresh');
    view.unmount(); render(<QuizzesAdminPage />);
    expect(await screen.findByDisplayValue('Keep dirty question on refresh')).toBeInTheDocument();
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it.each(['answers', 'explanation', 'type', 'points', 'text', 'choice-order', 'choice-text', 'choice-id', 'choice-count', 'question-order'] as const)('blocks recovery writes when saved %s changed under the same entity IDs', async (change) => {
    setupApi(); const view = render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Retained conflicting edit' } });
    view.unmount();
    const changedQuestion = { ...initialQuestion,
      ...(change === 'explanation' ? { explanation: 'Saved explanation changed elsewhere' } : {}),
      ...(change === 'type' ? { type: 'multiple_choice' } : {}),
      ...(change === 'points' ? { points: 2 } : {}),
      ...(change === 'text' ? { text: 'Saved question changed elsewhere' } : {}),
      ...(change === 'question-order' ? { order_index: 3 } : {}),
      choices: initialQuestion.choices.filter((_, index) => change !== 'choice-count' || index === 0).map((choice, index) => ({ ...choice,
        ...(change === 'answers' ? { is_correct: !choice.is_correct } : {}),
        ...(change === 'choice-order' ? { order_index: 1 - index } : {}),
        ...(change === 'choice-text' ? { text: `Changed saved choice ${index}` } : {}),
        ...(change === 'choice-id' && index === 0 ? { id: ids.choice3 } : {}),
      })),
    };
    const changedQuiz = { ...quiz, questions: [changedQuestion] };
    setupApi(changedQuiz, changedQuiz); render(<QuizzesAdminPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Сохранённый вопрос изменился');
    expect(screen.getByText('Retained conflicting edit')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
    expect(apiMock.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Отменить изменения' }));
    await selectQuiz(); fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    expect(within(dialog).getByRole('textbox', { name: 'Текст вопроса' })).toHaveValue(changedQuestion.text);
  });

  it.each(['success', 'failure'] as const)('ignores old grouped body parsing after a new session load (%s)', async (newOutcome) => {
    let resolveBody!: (value: typeof grouped) => void;
    const body = new Promise<typeof grouped>((resolve) => { resolveBody = resolve; });
    authMock.user = { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' };
    setupApi(); apiMock.get.mockResolvedValueOnce({ data: body });
    const view = render(<QuizzesAdminPage />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
    if (newOutcome === 'failure') apiMock.get.mockRejectedValueOnce(new Error('Current tenant unavailable'));
    authMock.user = { ...authMock.user, tenant_id: 'tenant-2' }; view.rerender(<QuizzesAdminPage />);
    if (newOutcome === 'failure') await screen.findByRole('button', { name: 'Повторить' });
    else await screen.findByRole('button', { name: /Курс 1/ });
    await act(async () => { resolveBody({ ...grouped, courses: [{ ...grouped.courses[0], title: 'Foreign delayed body' }] }); await body; });
    expect(screen.queryByRole('button', { name: /Foreign delayed body/ })).not.toBeInTheDocument();
    if (newOutcome === 'failure') expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
    else expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
  });

  it('ignores an old save body after the new actor opens a different dirty modal', async () => {
    let resolveBody!: (value: typeof quiz) => void;
    const body = new Promise<typeof quiz>((resolve) => { resolveBody = resolve; });
    authMock.user = { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' };
    setupApi(); apiMock.put.mockResolvedValueOnce({ data: body });
    const view = render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Old actor pending body' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    authMock.user = { ...authMock.user, user_id: 'author-2' }; view.rerender(<QuizzesAdminPage />);
    await selectQuiz(); fireEvent.click(screen.getByRole('button', { name: 'Создать вопрос' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'New actor unsaved question' } });
    await act(async () => { resolveBody({ ...quiz, title: 'Foreign saved body' }); await body; });
    expect(screen.getByDisplayValue('New actor unsaved question')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Foreign saved body' })).not.toBeInTheDocument();
  });

  it('rejects the previous session even when the same actor logs back in', async () => {
    setupApi(); const view = render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Previous session private draft' } });
    authMock.accessToken = ''; view.rerender(<QuizzesAdminPage />);
    authMock.accessToken = 'next-session-token'; view.rerender(<QuizzesAdminPage />);
    await screen.findByRole('button', { name: /Курс 1/ });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('Previous session private draft')).not.toBeInTheDocument();
  });

  it.each(['actor', 'tenant', 'session'] as const)('ignores a deferred grouped read after a mounted %s switch', async (change) => {
    let resolveOld!: (value: { data: typeof grouped }) => void;
    const oldRead = new Promise<{ data: typeof grouped }>((resolve) => { resolveOld = resolve; });
    authMock.user = { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' };
    setupApi(); apiMock.get.mockReturnValueOnce(oldRead);
    const view = render(<QuizzesAdminPage />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
    if (change === 'session') authMock.sessionEpoch += 1;
    else authMock.user = { ...authMock.user, ...(change === 'actor' ? { user_id: 'author-2' } : { tenant_id: 'tenant-2' }) };
    view.rerender(<QuizzesAdminPage />);
    await screen.findByRole('button', { name: /Курс 1/ });
    await act(async () => { resolveOld({ data: { ...grouped, courses: [{ ...grouped.courses[0], title: 'Foreign delayed course' }] } }); await oldRead; });
    expect(screen.queryByRole('button', { name: /Foreign delayed course/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Курс 1/ })).toBeInTheDocument();
  });

  it.each(['success', 'failure'] as const)('does not close or overwrite a new tenant question editor when an old save finishes (%s)', async (outcome) => {
    let resolveOld!: (value: { data: typeof quiz }) => void;
    let rejectOld!: (reason: Error) => void;
    const oldSave = new Promise<{ data: typeof quiz }>((resolve, reject) => { resolveOld = resolve; rejectOld = reject; });
    authMock.user = { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' };
    setupApi(); apiMock.put.mockReturnValueOnce(oldSave);
    const view = render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Old tenant save' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    authMock.user = { ...authMock.user, tenant_id: 'tenant-2' }; view.rerender(<QuizzesAdminPage />);
    await selectQuiz(); fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'New tenant unsaved edit' } });
    toastMock.success.mockClear(); toastMock.error.mockClear();
    await act(async () => {
      if (outcome === 'success') resolveOld({ data: { ...quiz, title: 'Foreign saved quiz' } });
      else rejectOld(new Error('Old tenant save failed'));
      await oldSave.catch(() => undefined);
    });
    expect(screen.getByDisplayValue('New tenant unsaved edit')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled();
    expect(screen.queryByRole('heading', { name: 'Foreign saved quiz' })).not.toBeInTheDocument();
    expect(toastMock.success).not.toHaveBeenCalled(); expect(toastMock.error).not.toHaveBeenCalled();
  });

  it('retains a new unsaved question through same-origin client route transitions without persisting it', async () => {
    function ClientNavigationHarness() {
      const [path, setPath] = useState('/quizzes');
      return <><a href={path === '/quizzes' ? '/courses' : '/quizzes'} onClick={(event) => { event.preventDefault(); const next = path === '/quizzes' ? '/courses' : '/quizzes'; window.history.pushState({}, '', next); setPath(next); }}>Client navigation</a>{path === '/quizzes' ? <QuizzesAdminPage /> : <p>Other route</p>}</>;
    }
    setupApi(); render(<ClientNavigationHarness />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Создать вопрос' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый вопрос' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'New draft retained' } });
    fireEvent.click(screen.getByRole('link', { name: 'Client navigation' }));
    expect(screen.getByText('Other route')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Client navigation' }));
    const restored = await screen.findByRole('dialog', { name: 'Новый вопрос' });
    expect(within(restored).getByDisplayValue('New draft retained')).toBeInTheDocument();
    expect(within(restored).getByText(/Несохранённые правки восстановлены/)).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.put).not.toHaveBeenCalled();
    fireEvent.click(within(restored).getByRole('button', { name: 'Отмена' }));
    fireEvent.click(within(restored).getByRole('button', { name: 'Отменить изменения' }));
    fireEvent.click(screen.getByRole('link', { name: 'Client navigation' }));
    fireEvent.click(screen.getByRole('link', { name: 'Client navigation' }));
    await screen.findByRole('button', { name: /Курс 1/ });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it.each(['actor', 'tenant', 'role', 'session'] as const)('does not restore a retained question draft after %s identity changes', async (change) => {
    authMock.user = { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' };
    setupApi(); const view = render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Private unsaved draft' } });
    view.unmount();
    if (change === 'actor') authMock.user = { ...authMock.user, user_id: 'author-2' };
    if (change === 'tenant') authMock.user = { ...authMock.user, tenant_id: 'tenant-2' };
    if (change === 'role') authMock.user = { ...authMock.user, role: 'student' };
    if (change === 'session') authMock.sessionEpoch += 1;
    render(<QuizzesAdminPage />);
    await screen.findByRole('button', { name: /Курс 1/ });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('Private unsaved draft')).not.toBeInTheDocument();
  });

  it('retains a draft without offering a write when its saved question is no longer available', async () => {
    setupApi(); const view = render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Draft for missing question' } });
    view.unmount(); setupApi({ ...quiz, questions: [] }, { ...quiz, questions: [] });
    render(<QuizzesAdminPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Несохранённый черновик вопроса сохранён в памяти');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(apiMock.put).not.toHaveBeenCalled();
    await selectQuiz();
    expect(screen.getByRole('button', { name: 'Создать вопрос' })).toBeDisabled();
    setupApi(); fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByDisplayValue('Draft for missing question')).toBeInTheDocument();
  });

  it('retains question text, explanation and choice IDs across Back/Forward route unmounts', async () => {
    window.history.replaceState({}, '', '/courses');
    window.history.pushState({}, '', '/quizzes');
    function HistoryHarness() {
      const [path, setPath] = useState(window.location.pathname);
      useEffect(() => {
        const onPopState = () => setPath(window.location.pathname);
        window.addEventListener('popstate', onPopState);
        return () => window.removeEventListener('popstate', onPopState);
      }, []);
      return path === '/quizzes' ? <QuizzesAdminPage /> : <p>Other route</p>;
    }
    setupApi(); render(<HistoryHarness />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    let dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Retain across history' } });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Пояснение после ответа' }), { target: { value: 'Retained explanation' } });
    fireEvent.change(within(dialog).getByDisplayValue('Старый правильный ответ'), { target: { value: 'Retained choice' } });
    act(() => window.history.back());
    await screen.findByText('Other route');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    act(() => window.history.forward());
    dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    expect(within(dialog).getByDisplayValue('Retain across history')).toBeInTheDocument();
    expect(within(dialog).getByDisplayValue('Retained explanation')).toBeInTheDocument();
    expect(within(dialog).getByDisplayValue('Retained choice')).toBeInTheDocument();
    expect(within(dialog).getByRole('status')).toHaveTextContent('Есть несохранённые изменения вопроса');
    expect(apiMock.put).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith(`/v1/quizzes/${ids.quiz}/questions/${ids.question}`, expect.objectContaining({ text: 'Retain across history' })));
    expect(apiMock.put.mock.calls[0][1].choices[0]).toMatchObject({ id: ids.choice1, text: 'Retained choice' });
  });

  beforeEach(() => {
    vi.clearAllMocks();
    clearQuestionDraft();
    window.history.replaceState({}, '', '/quizzes');
    authMock.accessToken = 'test-token';
    authMock.sessionEpoch = 1;
    authMock.user = null;
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

  it('shows saved/dirty question state and requires explicit discard on cancel', async () => {
    setupApi(); render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    expect(within(dialog).getByRole('status')).toHaveTextContent('Вопрос сохранён');
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Unsaved question' } });
    expect(within(dialog).getByRole('status')).toHaveTextContent('Есть несохранённые изменения вопроса');
    const unload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Отменить несохранённые изменения вопроса?');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Продолжить редактирование' }));
    expect(within(dialog).getByDisplayValue('Unsaved question')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отменить изменения' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it('protects a new unsaved question instead of treating it as a saved snapshot', async () => {
    setupApi(); render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Создать вопрос' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый вопрос' });
    expect(within(dialog).getByRole('status')).toHaveTextContent('Новый вопрос — не сохранён');
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'New unsaved question' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(within(dialog).getByRole('alert')).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('selects the real lesson quiz from the context link and keeps stable question anchors', async () => {
    window.history.replaceState({}, '', `/quizzes?lessonId=${ids.lesson}`);
    setupApi(); render(<QuizzesAdminPage />);
    expect(await screen.findByRole('heading', { name: 'Тест урока' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Редактировать урок' })).toHaveAttribute('href', `/courses/${ids.course}/edit?lessonId=${ids.lesson}`);
    expect(screen.getByRole('link', { name: 'Открыть урок' })).toHaveAttribute('href', `/courses/${ids.course}?lessonId=${ids.lesson}`);
    expect(screen.getByRole('link', { name: 'Вопрос 1: Старый вопрос' })).toHaveAttribute('href', `#question-${ids.question}`);
    expect(screen.getByRole('article', { name: 'Вопрос 1' })).toHaveAttribute('id', `question-${ids.question}`);
    expect(screen.queryByRole('button', { name: /Вариант [AB]/ })).not.toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledTimes(1);
  });

  it('keeps failed question saves dirty and exposes the actionable server message', async () => {
    setupApi(); apiMock.put.mockRejectedValue(new Error('Question changed; reload the saved version'));
    render(<QuizzesAdminPage />); await selectQuiz();
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование вопроса' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст вопроса' }), { target: { value: 'Keep this edit' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith(expect.any(String), { description: 'Question changed; reload the saved version' }));
    expect(within(dialog).getByDisplayValue('Keep this edit')).toBeInTheDocument();
    expect(within(dialog).getByRole('status')).toHaveTextContent('Есть несохранённые изменения вопроса');
  });

  it('preselects only the known lesson when its saved quiz is absent, without creating anything', async () => {
    window.history.replaceState({}, '', `/quizzes?lessonId=${ids.lesson}`);
    setupApi(quiz, null as any); render(<QuizzesAdminPage />);
    expect(await screen.findByLabelText('Курс')).toHaveValue(ids.course);
    expect(screen.getByLabelText('Модуль')).toHaveValue(ids.module);
    expect(screen.getByLabelText('Урок')).toHaveValue(ids.lesson);
    expect(screen.getByRole('button', { name: 'Создать' })).toBeDisabled();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('keeps the existing explicit quiz approval command authoritative', async () => {
    setupApi({ ...quiz, review_status: 'approved' } as typeof quiz, { ...quiz, review_status: 'needs_review' } as typeof quiz);
    render(<QuizzesAdminPage />); await selectQuiz();
    expect(screen.queryByText('Одобрено')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'authenticatedUi.quizUi.approveAfterReview' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(`/v1/quizzes/${ids.quiz}/approve`));
    expect(await screen.findByText('Одобрено')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'authenticatedUi.quizUi.approveAfterReview' })).not.toBeInTheDocument();
  });

  it('distinguishes load failure from an empty saved bank and retries', async () => {
    setupApi(); apiMock.get.mockRejectedValueOnce(new Error('Network down'));
    render(<QuizzesAdminPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить рабочую область');
    expect(screen.queryByText('authenticatedUi.quizUi.empty')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('button', { name: /Курс 1/ })).toBeInTheDocument();
  });

  it('exposes accessible labels for quiz configuration and AI draft controls', async () => {
    setupApi(quiz, null as any);
    render(<QuizzesAdminPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'quiz.create' }));

    expect(screen.getByLabelText('Курс')).toHaveAttribute('id', 'new-quiz-course');
    expect(screen.getByLabelText('Модуль')).toHaveAttribute('id', 'new-quiz-module');
    expect(screen.getByLabelText('Урок')).toHaveAttribute('id', 'new-quiz-lesson');
    expect(screen.getByLabelText('Тест')).toHaveAttribute('id', 'new-quiz-title');
    expect(screen.getByLabelText('quiz.passScore')).toHaveAttribute('id', 'new-quiz-pass-score');
    expect(screen.getByLabelText(/quiz\.timeLimit/)).toHaveAttribute('id', 'new-quiz-time-limit');
    expect(screen.queryByLabelText('quiz.timeLeft')).not.toBeInTheDocument();
    expect(screen.getByLabelText('authenticatedUi.quizUi.attemptLimit')).toHaveAttribute('id', 'new-quiz-attempt-limit');

    fireEvent.change(screen.getByLabelText('Курс'), { target: { value: ids.course } });
    fireEvent.change(screen.getByLabelText('Модуль'), { target: { value: ids.module } });
    fireEvent.change(screen.getByLabelText('Урок'), { target: { value: ids.lesson } });
    expect(screen.getByLabelText('authenticatedUi.quizUi.difficulty')).toHaveAttribute('id', 'ai-quiz-difficulty');
    expect(screen.getByLabelText('authenticatedUi.quizUi.preferences')).toHaveAttribute('id', 'ai-quiz-preferences');
  });

  it('uses the configured time-limit label in the static quiz summary', async () => {
    setupApi({ ...quiz, time_limit: 20 }, { ...quiz, time_limit: 20 });
    render(<QuizzesAdminPage />);
    await selectQuiz();
    expect(screen.getByText('quiz.timeLimit')).toBeInTheDocument();
    expect(screen.queryByText('quiz.timeLeft')).not.toBeInTheDocument();
  });

  it('keeps quiz creation disabled for a whitespace-only title', async () => {
    setupApi(quiz, null as any);
    render(<QuizzesAdminPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'quiz.create' }));
    fireEvent.change(screen.getByLabelText('Курс'), { target: { value: ids.course } });
    fireEvent.change(screen.getByLabelText('Модуль'), { target: { value: ids.module } });
    fireEvent.change(screen.getByLabelText('Урок'), { target: { value: ids.lesson } });
    fireEvent.change(screen.getByLabelText('Тест'), { target: { value: '   ' } });
    expect(screen.getByRole('button', { name: 'Создать' })).toBeDisabled();
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
    expect(within(dialog).getByLabelText('Вариант 1…')).toHaveAttribute('id', 'choice-text-0');
    expect(within(dialog).getByLabelText('Вариант 2…')).toHaveAttribute('id', 'choice-text-1');

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
