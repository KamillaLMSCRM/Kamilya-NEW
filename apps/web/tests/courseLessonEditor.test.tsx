import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));
const confirmMock = vi.hoisted(() => vi.fn().mockResolvedValue(false));
const routerPushMock = vi.hoisted(() => vi.fn());

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'course-1' }),
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
    }[key] ?? key),
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));

vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: confirmMock, dialog: null }),
}));

vi.mock('@/components/ui/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/ai/AIChatPanel', () => ({ AIChatPanel: () => null }));

import CourseEditPage from '@/app/courses/[id]/edit/page';
import { useAuthStore } from '@/store/authStore';

const course = {
  id: 'course-1',
  title: 'Курс по безопасности',
  description: '',
  status: 'draft',
  ai_generated: false,
  review_status: 'approved' as const,
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

function setupFetch(patchStatus = 200, courseStructure = structure) {
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/v1/courses/course-1/structure')) return jsonResponse(courseStructure);
    if (url.endsWith('/v1/courses/course-1')) return jsonResponse(course);
    if (url.includes('/v1/lessons/lesson-1') && init?.method !== 'PATCH') {
      return jsonResponse(lesson);
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
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      accessToken: 'test-token',
      user: null,
      initialized: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
