import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'course-1' }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: (key: string) => key,
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));

vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(false), dialog: null }),
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
  content: '# Старое содержание',
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
  const editButtons = screen.getAllByRole('button', { name: 'Редактировать' });
  fireEvent.click(editButtons[editButtons.length - 1]);
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

  it('loads the lesson into a wide modal and PATCHes title plus content', async () => {
    setupFetch();
    render(<CourseEditPage />);

    await screen.findByText('Введение');
    openLessonEditor();

    const dialog = await screen.findByRole('dialog', { name: 'Редактирование урока' });
    expect(dialog.className).toContain('max-w-5xl');
    expect(dialog.className).toContain('overflow-hidden');
    expect(dialog.className).toContain('flex-col');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/lessons/lesson-1'),
      expect.objectContaining({ method: 'GET' }),
    );
    const contentEditor = within(dialog).getByRole('textbox', { name: 'Содержание урока' });
    expect(contentEditor.className).toContain('text-base');
    expect(contentEditor.className).toContain('leading-7');
    expect(contentEditor.className).toContain('flex-1');
    expect(contentEditor.className).toContain('resize-none');
    expect(contentEditor.className).not.toContain('font-mono');

    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Название урока' }), {
      target: { value: 'Новое название' },
    });
    fireEvent.change(contentEditor, {
      target: { value: '# Новый текст' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'common.save' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(patchCall).toBeDefined();
    expect(JSON.parse((patchCall?.[1] as RequestInit).body as string)).toEqual({
      title: 'Новое название',
      content: '# Новый текст',
    });
    expect(screen.getByText('Новое название')).toBeInTheDocument();
  });

  it('keeps the lesson modal open when PATCH fails', async () => {
    setupFetch(500);
    render(<CourseEditPage />);

    await screen.findByText('Введение');
    openLessonEditor();
    const dialog = await screen.findByRole('dialog', { name: 'Редактирование урока' });

    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Содержание урока' }), {
      target: { value: '# Исправленный текст' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'common.save' }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalled());
    expect(screen.getByRole('dialog', { name: 'Редактирование урока' })).toBeInTheDocument();
    expect(within(screen.getByRole('dialog')).getByDisplayValue('# Исправленный текст')).toBeInTheDocument();
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
