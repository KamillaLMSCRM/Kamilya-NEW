import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));
const confirmMock = vi.hoisted(() => vi.fn().mockResolvedValue(false));
const routerPushMock = vi.hoisted(() => vi.fn());
const routeMock = vi.hoisted(() => ({ courseId: 'course-1' }));
const chatHarness = vi.hoisted(() => ({ reload: null as (() => Promise<void>) | null }));
const correctionHarness = vi.hoisted(() => ({ enabled: false, props: null as any }));

vi.mock('@/features/methodologist-workbench/LessonCorrectionPanel', async () => {
  const { forwardRef } = await import('react');
  return { default: forwardRef(function CorrectionHarness(props: any, _ref) {
    void _ref;
    correctionHarness.props = props;
    if (!correctionHarness.enabled) return null;
    return <div><button onClick={() => props.onApplied({ course_id: 'course-1', lesson_id: 'lesson-1' }, '# AI-правка', lesson.content)}>Apply synthetic correction</button><button onClick={() => props.onApplyingChange(true)}>Begin correction</button><button onClick={() => props.onReload()}>Reload synthetic correction</button></div>;
  }) };
});

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: routeMock.courseId }),
  useRouter: () => ({ push: routerPushMock, replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => ({
      'authenticatedUi.editor.approval': 'Согласование',
      'authenticatedUi.editor.publish': 'Опубликовать',
      'authenticatedUi.editor.assistant': 'AI-помощник',
      'authenticatedUi.editor.moveModuleUp': 'Переместить модуль выше',
      'authenticatedUi.editor.moveModuleDown': 'Переместить модуль ниже',
      'authenticatedUi.editor.moveLessonUp': 'Переместить урок выше',
      'authenticatedUi.editor.moveLessonDown': 'Переместить урок ниже',
      'authenticatedUi.editor.lessonAssistantTitle': 'AI-помощник по этому уроку',
      'authenticatedUi.editor.openLessonAssistant': 'Открыть AI-помощника для урока {title}',
      'authenticatedUi.editor.deleteLesson': 'Удалить урок {title}',
      'authenticatedUi.editor.modalTitle': 'Редактирование урока',
      'authenticatedUi.editor.modalDescription': 'Измените название и содержание. Форматирование Markdown сохранится.',
      'authenticatedUi.editor.lessonTitle': 'Название урока',
      'authenticatedUi.editor.lessonTitlePlaceholder': 'Например, Введение в информационную безопасность…',
      'authenticatedUi.editor.lessonContent': 'Содержание урока',
      'authenticatedUi.editor.lessonContentPlaceholder': 'Введите содержание урока…',
      'authenticatedUi.editor.outline': 'Структура курса',
      'authenticatedUi.editor.workspaceTitle': 'Рабочая область урока',
      'authenticatedUi.editor.viewMode': 'Режим просмотра урока',
      'authenticatedUi.editor.editMode': 'Редактор',
      'authenticatedUi.editor.previewMode': 'Предпросмотр',
      'authenticatedUi.editor.emptySelection': 'Выберите урок',
      'authenticatedUi.editor.selectLesson': 'Выберите урок слева',
      'authenticatedUi.editor.lessonProperties': 'Урок',
      'authenticatedUi.editor.contentType': 'Тип содержимого',
      'authenticatedUi.editor.learnerPreview': 'Открыть как обучающийся',
      'authenticatedUi.editor.unsavedChanges': 'Есть несохранённые изменения',
      'authenticatedUi.editor.unsavedTitle': 'Изменения не сохранены',
      'authenticatedUi.editor.unsavedDescription': 'Изменения будут потеряны',
      'authenticatedUi.editor.leaveWithoutSaving': 'Продолжить без сохранения',
      'authenticatedUi.editor.discard': 'Отменить изменения',
      'common.edit': 'Редактировать',
      'common.saveFailed': 'Не удалось сохранить',
      'common.deleteFailed': 'Не удалось удалить',
    }[key] ?? key),
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));

vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: confirmMock, dialog: null }),
}));

vi.mock('@/components/ui/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/ai/AIChatPanel', () => ({ AIChatPanel: (props: { onLessonApplied: () => Promise<void> }) => { chatHarness.reload = props.onLessonApplied; return null; } }));

import CourseEditPage from '@/app/courses/[id]/edit/page';
import { useAuthStore } from '@/store/authStore';

const course = {
  id: 'course-1',
  title: 'Курс по безопасности',
  description: '',
  status: 'draft',
  ai_generated: false,
  review_status: 'approved' as 'approved' | 'pending' | 'needs_changes',
  source_analysis: {},
};
const blueprintPendingCourse = {
  ...course,
  review_status: 'pending' as const,
  source_analysis: { blueprint: { id: 'blueprint-1' } },
};

const structure = {
  modules: [{
    id: 'module-1',
    title: 'Модуль 1',
    description: '',
    order_index: 0,
    lessons: [{
      id: 'lesson-1',
      title: 'Введение',
      content_type: 'text',
      order_index: 0,
    }],
  }],
};

const structureWithTwoLessons = {
  modules: [{
    ...structure.modules[0],
    lessons: [
      ...structure.modules[0].lessons,
      {
        id: 'lesson-2',
        title: 'Практика',
        content_type: 'text',
        order_index: 1,
      },
    ],
  }],
};

const lesson = {
  id: 'lesson-1',
  title: 'Введение',
  content: '# Старое содержание\n\n## Характеристики\n\n| Параметр | Значение |\n| --- | --- |\n| Срок | 30 дней |',
  content_type: 'text',
  order_index: 0,
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function setupFetch(patchStatus = 200, courseStructure = structure, lessonOverride = lesson, courseOverride = course, modulePatch: 'ok' | 'error' | 'network' = 'ok', deletePatch: 'ok' | 'error' | 'network' = 'ok') {
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'DELETE' && (url.includes('/v1/modules/module-1') || url.includes('/v1/lessons/lesson-1'))) {
      if (deletePatch === 'network') throw new Error('network down');
      return jsonResponse(deletePatch === 'ok' ? {} : { detail: 'Delete failed' }, deletePatch === 'ok' ? 200 : 500);
    }
    if (url.includes('/v1/modules/module-1') && init?.method === 'PATCH') {
      if (modulePatch === 'network') throw new Error('network down');
      return jsonResponse(modulePatch === 'ok' ? { ...structure.modules[0], title: 'Server module title' } : { detail: 'Save failed' }, modulePatch === 'ok' ? 200 : 500);
    }
    if (url.includes('/v1/courses/course-1/structure')) return jsonResponse(courseStructure);
    if (url.endsWith('/v1/courses/course-1/review')) return jsonResponse({ ...courseOverride, review_status: 'approved' });
    if (url.endsWith('/v1/courses/course-1/publish')) return jsonResponse({ ...courseOverride, status: 'published', review_status: 'approved' });
    if (url.endsWith('/v1/courses/course-1')) return jsonResponse(courseOverride);
    if (url.includes('/v1/lessons/lesson-1') && init?.method !== 'PATCH') {
      return jsonResponse(lessonOverride);
    }
    if (url.includes('/v1/lessons/lesson-2') && init?.method !== 'PATCH') {
      return jsonResponse({ ...lesson, id: 'lesson-2', title: 'Практика', content: '## Практика' });
    }
    if (url.includes('/v1/lessons/lesson-1') && init?.method === 'PATCH') {
      return jsonResponse(
        patchStatus === 200 ? { ...lesson, title: 'Новое название', content: '# Новый текст' } : { detail: 'Save failed' },
        patchStatus,
      );
    }
    return jsonResponse({ detail: 'Unexpected request' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
}

function openLessonEditor() {
  fireEvent.click(screen.getByRole('button', { name: 'Введение' }));
}

describe('course lesson editor', () => {
  it('preserves an unsaved lesson through same-actor token rotation and uses the latest token to save', async () => {
    setupFetch(); render(<CourseEditPage />); await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), { target: { value: 'Keep dirty lesson on refresh' } });
    act(() => useAuthStore.setState({ accessToken: 'rotated-token' }));
    expect(screen.getByDisplayValue('Keep dirty lesson on refresh')).toBeInTheDocument();
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/v1/lessons/lesson-1'), expect.objectContaining({ method: 'PATCH', headers: expect.objectContaining({ Authorization: 'Bearer rotated-token' }) })));
  });

  it.each(['success', 'failure'] as const)('rejects an obsolete same-scope metadata generation after a newer refresh (%s)', async (oldOutcome) => {
    let resolveOld!: (response: Response) => void;
    let rejectOld!: (error: Error) => void;
    const oldRead = new Promise<Response>((resolve, reject) => { resolveOld = resolve; rejectOld = reject; });
    setupFetch(); const implementation = fetchMock.getMockImplementation()!;
    let courseReads = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/v1/courses/course-1')) {
        courseReads += 1;
        if (courseReads === 2) return oldRead;
        if (courseReads > 2) return Promise.resolve(jsonResponse({ ...course, title: 'Latest metadata generation' }));
      }
      return implementation(input, init);
    });
    render(<CourseEditPage />); await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), { target: { value: 'Saved edit' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));
    await waitFor(() => expect(courseReads).toBe(2));
    await act(async () => { await chatHarness.reload!(); });
    await screen.findByRole('link', { name: 'Latest metadata generation' });
    await act(async () => {
      if (oldOutcome === 'success') resolveOld(jsonResponse({ ...course, title: 'Obsolete generation' }));
      else rejectOld(new Error('Obsolete generation failed'));
      await oldRead.catch(() => undefined);
    });
    expect(screen.getByRole('link', { name: 'Latest metadata generation' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Obsolete generation' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeEnabled();
  });

  it.each([
    ['actor', 'success', 'success'], ['actor', 'failure', 'success'],
    ['actor', 'success', 'failure'], ['actor', 'failure', 'failure'],
    ['course', 'success', 'success'], ['course', 'failure', 'success'],
    ['course', 'success', 'failure'], ['course', 'failure', 'failure'],
    ['tenant', 'success', 'success'], ['tenant', 'failure', 'success'],
    ['tenant', 'success', 'failure'], ['tenant', 'failure', 'failure'],
    ['session', 'success', 'success'], ['session', 'failure', 'success'],
  ] as const)('rejects an old post-save %s-scope readback (%s) after the new scope load (%s)', async (scopeChange, oldOutcome, newOutcome) => {
    let resolveOld!: (response: Response) => void;
    let rejectOld!: (reason: Error) => void;
    const oldRead = new Promise<Response>((resolve, reject) => { resolveOld = resolve; rejectOld = reject; });
    const user = { user_id: 'author-1', tenant_id: 'tenant-1', tenant: null, role: 'methodologist', full_name: 'Author', email: null, telegram_id: '' };
    useAuthStore.setState({ user });
    setupFetch();
    const implementation = fetchMock.getMockImplementation()!;
    let phase: 'old' | 'new' = 'old';
    let courseReads = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (/\/v1\/courses\/course-[12]$/.test(url)) {
        if (phase === 'old' && ++courseReads > 1) return oldRead;
        if (phase === 'new') return Promise.resolve(jsonResponse(newOutcome === 'failure' ? { detail: 'New scope unavailable' } : { ...course, id: routeMock.courseId, title: 'Current scope course' }, newOutcome === 'failure' ? 503 : 200));
      }
      if (phase === 'new' && url.endsWith('/structure')) return Promise.resolve(jsonResponse(structure));
      return implementation(input, init);
    });
    const view = render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), { target: { value: 'Saved before scope change' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));
    await waitFor(() => expect(courseReads).toBe(2));
    phase = 'new';
    act(() => {
      if (scopeChange === 'course') routeMock.courseId = 'course-2';
      if (scopeChange === 'actor') useAuthStore.setState({ accessToken: 'new-token', user: { ...user, user_id: 'author-2' } });
      if (scopeChange === 'tenant') useAuthStore.setState({ user: { ...user, tenant_id: 'tenant-2' } });
      if (scopeChange === 'session') useAuthStore.setState((state) => ({ sessionEpoch: state.sessionEpoch + 1 }));
      view.rerender(<CourseEditPage />);
    });
    if (newOutcome === 'failure') await screen.findByRole('button', { name: 'Повторить' });
    else await screen.findByRole('link', { name: 'Current scope course' });
    await act(async () => {
      if (oldOutcome === 'success') resolveOld(jsonResponse({ ...course, title: 'Obsolete readback course' }));
      else rejectOld(new Error('Old scope failed late'));
      await oldRead.catch(() => undefined);
    });
    expect(screen.queryByRole('link', { name: 'Obsolete readback course' })).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('Saved before scope change')).not.toBeInTheDocument();
    if (newOutcome === 'failure') {
      expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Опубликовать' })).not.toBeInTheDocument();
    } else {
      expect(screen.getByRole('link', { name: 'Current scope course' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeEnabled();
    }
  });

  it('formats selected canonical text, keeps the dirty guard, and renders it with the existing preview', async () => {
    setupFetch(); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    const textarea = await screen.findByRole('textbox', { name: 'Содержание урока' }) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Сохранить смысл' } });
    textarea.setSelectionRange(0, 9);
    fireEvent.click(screen.getByRole('button', { name: 'Полужирный' }));
    expect(textarea).toHaveValue('**Сохранить** смысл');
    expect(textarea).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр' }));
    expect(screen.getByText('Сохранить').tagName).toBe('STRONG');
    expect(screen.getByRole('button', { name: 'Предпросмотр' })).toHaveAttribute('aria-pressed', 'true');
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false);
  });

  it('keeps the selected lesson and its quiz context when next-lesson navigation is declined', async () => {
    setupFetch(200, structureWithTwoLessons); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), { target: { value: 'Unsaved' } });
    expect(screen.getByRole('link', { name: 'Вопросы этого урока' })).toHaveAttribute('href', '/quizzes?lessonId=lesson-1');
    fireEvent.click(screen.getByRole('button', { name: 'Следующий урок' }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(screen.getByDisplayValue('Unsaved')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Введение' })).toHaveAttribute('aria-current', 'true');
  });

  it('opens only a lesson from the loaded structure for a context deep link', async () => {
    window.history.replaceState({}, '', '/courses/course-1/edit?lessonId=lesson-2');
    setupFetch(200, structureWithTwoLessons); render(<CourseEditPage />);
    expect(await screen.findByDisplayValue('## Практика')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Практика' })).toHaveAttribute('aria-current', 'true');
  });

  it('offers retry instead of treating a failed structure read as an empty course', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Unavailable' }, 503)); vi.stubGlobal('fetch', fetchMock);
    render(<CourseEditPage />);
    expect(await screen.findByRole('button', { name: 'Повторить' })).toBeInTheDocument();
    expect(screen.queryByText('courses.noModules')).not.toBeInTheDocument();
    setupFetch(); fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('button', { name: 'Введение' })).toBeInTheDocument();
  });

  it('does not claim current approval if the post-save review status cannot be read', async () => {
    setupFetch(200, structure, lesson, { ...course, ai_generated: true });
    const implementation = fetchMock.getMockImplementation()!;
    let courseReads = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/v1/courses/course-1') && ++courseReads > 1) return Promise.resolve(jsonResponse({ detail: 'Unavailable' }, 503));
      return implementation(input, init);
    });
    render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), { target: { value: 'Saved edit' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument());
    expect(screen.queryByText('Одобрено')).not.toBeInTheDocument();
    expect(screen.queryByText('authenticatedUi.editor.reviewed')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeDisabled();
    expect(screen.getByDisplayValue('Saved edit')).toBeInTheDocument();
    expect(screen.queryByText('Есть несохранённые изменения')).not.toBeInTheDocument();
    expect(toastMock.success).toHaveBeenCalledWith('authenticatedUi.editor.lessonSaved');
  });

  it('names the module rename field for keyboard and screen-reader users', async () => {
    setupFetch();
    render(<CourseEditPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Редактировать' }));
    expect(screen.getByRole('textbox', { name: 'courses.moduleTitle' })).toHaveFocus();
  });

  it('keeps the module rename draft and reports a safe error when the PATCH returns HTTP 500', async () => {
    setupFetch(200, structure, lesson, course, 'error');
    render(<CourseEditPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Редактировать' }));
    const input = screen.getByRole('textbox', { name: 'courses.moduleTitle' });
    fireEvent.change(input, { target: { value: 'Новое имя модуля' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Не удалось сохранить'));
    expect(screen.getByRole('textbox', { name: 'courses.moduleTitle' })).toHaveValue('Новое имя модуля');
    expect(screen.queryByText('Server module title')).not.toBeInTheDocument();
  });

  it('renders the authoritative module title returned by a successful PATCH', async () => {
    setupFetch();
    render(<CourseEditPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Редактировать' }));
    const input = screen.getByRole('textbox', { name: 'courses.moduleTitle' });
    fireEvent.change(input, { target: { value: 'Черновое имя модуля' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));

    await waitFor(() => expect(screen.getByText('Server module title')).toBeInTheDocument());
    expect(screen.queryByRole('textbox', { name: 'courses.moduleTitle' })).not.toBeInTheDocument();
  });

  it('keeps the module rename draft and reports a safe error when the PATCH rejects', async () => {
    setupFetch(200, structure, lesson, course, 'network');
    render(<CourseEditPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Редактировать' }));
    const input = screen.getByRole('textbox', { name: 'courses.moduleTitle' });
    fireEvent.change(input, { target: { value: 'Новое имя модуля' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Не удалось сохранить'));
    expect(screen.getByRole('textbox', { name: 'courses.moduleTitle' })).toHaveValue('Новое имя модуля');
  });

  it('names the new-lesson title field for keyboard and screen-reader users', async () => {
    setupFetch();
    render(<CourseEditPage />);
    fireEvent.click(await screen.findByRole('button', { name: '+ courses.addLesson' }));
    expect(screen.getByRole('textbox', { name: 'courses.addLesson' })).toHaveFocus();
  });

  it('describes an empty module outline without claiming the course itself is missing', async () => {
    setupFetch(200, { modules: [] });
    render(<CourseEditPage />);
    expect(await screen.findByText('courses.noModules')).toBeInTheDocument();
    expect(screen.queryByText('courses.noCourses')).not.toBeInTheDocument();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    routeMock.courseId = 'course-1';
    chatHarness.reload = null;
    correctionHarness.enabled = false; correctionHarness.props = null;
    window.history.replaceState({}, '', '/courses/course-1/edit');
    useAuthStore.setState({
      accessToken: 'test-token',
      user: null,
      initialized: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('keeps lesson actions wrapped and reserves a wide editor before placing properties beside it', async () => {
    setupFetch(); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    await screen.findByRole('textbox', { name: 'Содержание урока' });
    const save = screen.getByRole('button', { name: 'common.save' });
    expect(save.parentElement).toHaveClass('flex-wrap', 'max-w-full');
    expect(save.parentElement?.parentElement).toHaveClass('flex-wrap', 'min-w-0');
    expect(screen.getByRole('group', { name: 'Режим просмотра урока' })).toHaveClass('flex-wrap');
    const grid = save.closest('.grid');
    expect(grid).toHaveClass('min-w-0', 'grid-cols-1', 'xl:grid-cols-[280px_minmax(0,1fr)]', '2xl:grid-cols-[minmax(280px,340px)_minmax(0,1fr)_280px]');
    expect(screen.getByRole('heading', { name: 'Структура курса' }).closest('.rounded-lg')).toHaveClass('min-w-0');
    expect(screen.getByRole('textbox', { name: 'courses.addModule' }).parentElement).toHaveClass('min-w-0', 'flex-wrap');
    expect(screen.getByRole('heading', { name: /^Урок$/ }).closest('aside')).toHaveClass('xl:col-span-2', '2xl:col-span-1');
  });

  it('offers explicit approval before publishing a blueprint-backed non-AI course', async () => {
    setupFetch(200, structure, lesson, blueprintPendingCourse); render(<CourseEditPage />);
    expect(await screen.findByRole('button', { name: 'authenticatedUi.editor.approveCourse' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Опубликовать' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'authenticatedUi.editor.approveCourse' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/course-1/review'),
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ review_status: 'approved' }) }),
    ));
    expect(await screen.findByRole('button', { name: 'Опубликовать' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Опубликовать' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/courses/course-1/publish'),
      expect.objectContaining({ method: 'POST' }),
    ));
  });

  it('keeps ordinary manual drafts publishable without a blueprint marker', async () => {
    setupFetch(200, structure, lesson, { ...course, review_status: 'pending', source_analysis: {} }); render(<CourseEditPage />);
    expect(await screen.findByRole('button', { name: 'Опубликовать' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'authenticatedUi.editor.approveCourse' })).not.toBeInTheDocument();
  });

  it('keeps the existing approval gate for AI-generated drafts', async () => {
    setupFetch(200, structure, lesson, { ...course, ai_generated: true, review_status: 'pending' }); render(<CourseEditPage />);
    expect(await screen.findByRole('button', { name: 'authenticatedUi.editor.approveCourse' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Опубликовать' })).not.toBeInTheDocument();
  });

  it('integrates a verified fresh correction without issuing a manual PATCH', async () => {
    correctionHarness.enabled = true; setupFetch(); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply synthetic correction' }));
    expect(screen.getByRole('textbox', { name: 'Содержание урока' })).toHaveValue('# AI-правка');
    expect(screen.queryByText('Есть несохранённые изменения')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false);
  });

  it('keeps the feature-OFF editor controls in a labeled accessible group', async () => {
    setupFetch(); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    await screen.findByRole('textbox', { name: 'Содержание урока' });
    expect(screen.getByRole('group', { name: 'courses.editCourse' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Apply synthetic correction' })).not.toBeInTheDocument();
  });

  it('suppresses only an exact duplicate first-level title in the editor preview', async () => {
    setupFetch(200, structure, { ...lesson, content: '# Введение\r\n\r\nТекст урока' }); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    await screen.findByRole('textbox', { name: 'Содержание урока' });
    fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр' }));
    expect(screen.getAllByRole('heading', { level: 1, name: 'Введение' })).toHaveLength(1);
    expect(screen.getByText('Текст урока')).toBeInTheDocument();
  });

  it('preserves later manual changes even if a correction callback arrives', async () => {
    correctionHarness.enabled = true; setupFetch(); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), { target: { value: '# Поздняя ручная правка' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply synthetic correction' }));
    expect(screen.getByRole('textbox', { name: 'Содержание урока' })).toHaveValue('# Поздняя ручная правка');
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
  });

  it('disables editor and lesson navigation during a correction write', async () => {
    correctionHarness.enabled = true; setupFetch(200, structureWithTwoLessons); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    fireEvent.click(await screen.findByRole('button', { name: 'Begin correction' }));
    expect(screen.getByRole('textbox', { name: 'Содержание урока' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Название урока' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Практика' })).toBeDisabled();
  });

  it('clears only the previous correction pointer on accepted lesson selection', async () => {
    correctionHarness.enabled = true; setupFetch(200, structureWithTwoLessons); render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' }); openLessonEditor();
    await screen.findByRole('button', { name: 'Apply synthetic correction' });
    window.history.replaceState({}, '', '/courses/course-1/edit?correction_plan=opaque-old-plan&other=keep#editor');
    fireEvent.click(screen.getByRole('button', { name: 'Практика' }));
    await screen.findByDisplayValue('## Практика');
    expect(new URL(window.location.href).searchParams.get('correction_plan')).toBeNull();
    expect(new URL(window.location.href).searchParams.get('other')).toBe('keep'); expect(window.location.hash).toBe('#editor');
  });

  it('loads the lesson into the full-page workspace and PATCHes title plus content', async () => {
    setupFetch();
    render(<CourseEditPage />);

    await screen.findByText('Введение');
    openLessonEditor();

    await screen.findByText('Рабочая область урока');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/lessons/lesson-1'),
      expect.objectContaining({ method: 'GET' }),
    );
    const contentEditor = screen.getByRole('textbox', { name: 'Содержание урока' });
    expect(contentEditor.className).toContain('text-base');
    expect(contentEditor.className).toContain('leading-7');
    expect(contentEditor.className).toContain('flex-1');
    expect(contentEditor.className).toContain('resize-y');
    expect(contentEditor.className).not.toContain('font-mono');
    fireEvent.change(screen.getByRole('textbox', { name: 'Название урока' }), {
      target: { value: 'Новое название' },
    });
    fireEvent.change(contentEditor, {
      target: { value: '# Новый текст' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));

    await waitFor(() => expect(screen.queryByText('Есть несохранённые изменения')).not.toBeInTheDocument());
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(patchCall).toBeDefined();
    expect(JSON.parse((patchCall?.[1] as RequestInit).body as string)).toEqual({
      title: 'Новое название',
      content: '# Новый текст',
    });
    expect(screen.getAllByText('Новое название')).toHaveLength(2);
  });

  it('keeps the lesson draft in the workspace when PATCH fails', async () => {
    setupFetch(500);
    render(<CourseEditPage />);

    await screen.findByText('Введение');
    openLessonEditor();
    await screen.findByText('Рабочая область урока');

    fireEvent.change(screen.getByRole('textbox', { name: 'Содержание урока' }), {
      target: { value: '# Исправленный текст' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalled());
    expect(screen.getByDisplayValue('# Исправленный текст')).toBeInTheDocument();
  });

  it('keeps the active draft when the user declines to discard it for another lesson', async () => {
    setupFetch(200, structureWithTwoLessons);
    render(<CourseEditPage />);

    await screen.findByRole('button', { name: 'Введение' });
    openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), {
      target: { value: '# Несохранённый текст' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Практика' }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Изменения не сохранены',
    })));
    expect(screen.getByDisplayValue('# Несохранённый текст')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/lessons/lesson-2'),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('keeps the active draft when the user declines learner preview navigation', async () => {
    setupFetch();
    render(<CourseEditPage />);

    await screen.findByRole('button', { name: 'Введение' });
    openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), {
      target: { value: '# Несохранённый текст' },
    });
    expect(screen.getByRole('button', { name: 'Опубликовать' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть как обучающийся' }));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      message: 'Изменения будут потеряны',
    })));
    expect(routerPushMock).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('# Несохранённый текст')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('link', { name: 'Согласование' }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(2));
    expect(routerPushMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('link', { name: 'Курс по безопасности' }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(3));
    expect(routerPushMock).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('# Несохранённый текст')).toBeInTheDocument();
  });

  it('guards internal navigation links rendered outside the editor subtree', async () => {
    setupFetch();
    render(<CourseEditPage />);

    await screen.findByRole('button', { name: 'Введение' });
    openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), {
      target: { value: '# Несохранённый текст' },
    });

    const sidebarLink = document.createElement('a');
    sidebarLink.href = '/courses';
    sidebarLink.textContent = 'Глобальная ссылка курсов';
    document.body.appendChild(sidebarLink);
    const navigationAllowed = fireEvent.click(sidebarLink);

    expect(navigationAllowed).toBe(false);
    await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      message: 'Изменения будут потеряны',
    })));
    expect(routerPushMock).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('# Несохранённый текст')).toBeInTheDocument();
    sidebarLink.remove();
  });

  it('warns about the active unsaved draft before deleting its lesson or module', async () => {
    setupFetch();
    render(<CourseEditPage />);

    await screen.findByRole('button', { name: 'Введение' });
    openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), {
      target: { value: '# Несохранённый текст' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Удалить урок {title}' }));
    await waitFor(() => expect(confirmMock).toHaveBeenLastCalledWith(expect.objectContaining({
      message: 'Изменения будут потеряны',
    })));

    fireEvent.click(screen.getAllByRole('button', { name: 'common.delete' })[0]);
    await waitFor(() => expect(confirmMock).toHaveBeenLastCalledWith(expect.objectContaining({
      message: 'Изменения будут потеряны',
    })));
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/lessons/lesson-1'),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('deletes the active lesson and closes its workspace after explicit confirmation', async () => {
    setupFetch();
    confirmMock.mockResolvedValueOnce(true);
    render(<CourseEditPage />);

    await screen.findByRole('button', { name: 'Введение' });
    openLessonEditor();
    await screen.findByRole('textbox', { name: 'Содержание урока' });
    fireEvent.click(screen.getByRole('button', { name: 'Удалить урок {title}' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/lessons/lesson-1'),
      expect.objectContaining({ method: 'DELETE' }),
    ));
    expect(screen.queryByRole('textbox', { name: 'Содержание урока' })).not.toBeInTheDocument();
    expect(screen.getByText('Выберите урок')).toBeInTheDocument();
  });

  it.each([
    ['HTTP 500', 'error'],
    ['network rejection', 'network'],
  ] as const)('retains the active lesson and draft when lesson DELETE fails with %s', async (_label, failure) => {
    setupFetch(200, structure, lesson, course, 'ok', failure);
    confirmMock.mockResolvedValueOnce(true);
    render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' });
    openLessonEditor();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Содержание урока' }), { target: { value: '# Несохранённый текст' } });
    fireEvent.click(screen.getByRole('button', { name: 'Удалить урок {title}' }));
    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Не удалось удалить'));
    expect(screen.getByDisplayValue('# Несохранённый текст')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Введение' })).toBeInTheDocument();
  });

  it.each([
    ['HTTP 500', 'error'],
    ['network rejection', 'network'],
  ] as const)('retains the module when module DELETE fails with %s', async (_label, failure) => {
    setupFetch(200, structure, lesson, course, 'ok', failure);
    confirmMock.mockResolvedValueOnce(true);
    render(<CourseEditPage />);
    await screen.findByRole('button', { name: 'Введение' });
    fireEvent.click(screen.getAllByRole('button', { name: 'common.delete' })[0]);
    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Не удалось удалить'));
    expect(screen.getByText('Модуль 1')).toBeInTheDocument();
  });

  it('persists a lesson move through the published lessons reorder route', async () => {
    setupFetch(200, structureWithTwoLessons);
    render(<CourseEditPage />);

    await screen.findByText('Практика');
    fireEvent.click(screen.getAllByRole('button', { name: 'Переместить урок ниже' })[0]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/v1/lessons/module-1/reorder'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(['lesson-2', 'lesson-1']),
        }),
      );
    });
  });
});
