import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
const confirmMock = vi.hoisted(() => vi.fn());
const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  searchParams: new URLSearchParams(),
}));
const context = vi.hoisted(() => ({
  lang: 'ru',
  epoch: 1,
  user: { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' } as {
    user_id: string; tenant_id: string; role: string;
  } | null,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: navigation.replace, push: navigation.push }),
  useSearchParams: () => navigation.searchParams,
}));
vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: () => ({ user: context.user, sessionEpoch: context.epoch }),
}));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    lang: context.lang,
    t: (key: string, params?: Record<string, string | number>) => {
      const messages: Record<string, unknown> = { ru, kk, en };
      let value: unknown = messages[context.lang];
      for (const part of key.split('.')) value = (value as Record<string, unknown>)?.[part];
      return String(value ?? key).replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? `{${name}}`));
    },
  }),
}));
vi.mock('@/components/ui/ConfirmDialog', () => ({
  useConfirm: () => ({ confirm: confirmMock, dialog: null }),
}));
vi.mock('@/components/ui/Toast', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

import CoursesPage from '@/app/courses/page';
import { courseCatalogCopy } from '@/features/course-catalog/copy';
import { toast } from '@/components/ui/Toast';

const draft = {
  id: 'draft-1', title: 'Информационная безопасность: правила работы с данными и документами организации',
  description: 'Рабочая программа обучения сотрудников', status: 'draft', delivery_type: 'native',
};
const published = { ...draft, id: 'published-1', title: 'Опубликованный курс', status: 'published', current_release_id: 'release-1' };
const blueprint = {
  id: 'kz-finance-information-security', title: 'Отраслевая основа', description: 'Основа для адаптации',
  audience: 'Сотрудники', estimated_ready_percent: 70,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function mockLists(courses: unknown[] = [draft]) {
  apiMock.get.mockImplementation((url: string) => Promise.resolve({
    data: url.startsWith('/v1/course-blueprints?') ? [blueprint] : courses,
  }));
}

function results(container: HTMLElement) {
  return container.querySelector<HTMLElement>('[data-course-catalog-results]')!;
}

describe('production course catalogue presentation', () => {
  it('opens courses beyond the first 100 through the existing server page contract', async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => ({ ...draft, id: `page-1-${index}`, title: `Course ${index + 1}` }));
    apiMock.get.mockImplementation((url: string) => Promise.resolve({ data: url.startsWith('/v1/course-blueprints?') ? [] : url.includes('page=2') ? [{ ...draft, title: 'Course 101' }] : firstPage }));
    render(<CoursesPage />);
    await screen.findByRole('heading', { name: 'Course 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
    expect(await screen.findByRole('heading', { name: 'Course 101' })).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/v1/courses?per_page=100&page=2');
    expect(navigation.push).toHaveBeenCalledWith('/courses?page=2', { scroll: false });
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Предыдущая страница' }));
    expect(await screen.findByRole('heading', { name: 'Course 1' })).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('restores the page with browser history and resets it when filters change', async () => {
    navigation.searchParams = new URLSearchParams('q=safety&status=draft&page=2');
    const { rerender } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    expect(apiMock.get).toHaveBeenCalledWith('/v1/courses?q=safety&status=draft&per_page=100&page=2');
    navigation.searchParams = new URLSearchParams('q=safety&status=draft');
    rerender(<CoursesPage />);
    await waitFor(() => expect(within(screen.getByRole('navigation', { name: 'Страницы каталога' })).getByRole('status')).toHaveTextContent('Страница 1'));
    navigation.searchParams = new URLSearchParams('q=safety&status=draft&page=2');
    rerender(<CoursesPage />);
    await waitFor(() => expect(within(screen.getByRole('navigation', { name: 'Страницы каталога' })).getByRole('status')).toHaveTextContent('Страница 2'));
    fireEvent.change(screen.getByLabelText('Статус'), { target: { value: 'published' } });
    expect(navigation.push).toHaveBeenLastCalledWith('/courses?q=safety&status=published', { scroll: false });
    await waitFor(() => expect(apiMock.get).toHaveBeenLastCalledWith('/v1/courses?q=safety&status=published&per_page=100'));
  });
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockReset();
    apiMock.post.mockReset();
    apiMock.delete.mockReset();
    confirmMock.mockReset();
    context.lang = 'ru';
    context.epoch = 1;
    context.user = { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' };
    navigation.replace.mockReset();
    navigation.push.mockReset();
    navigation.searchParams = new URLSearchParams();
    mockLists();
  });

  it('initializes the catalogue from a supported status deep link and keeps it in the URL', async () => {
    navigation.searchParams = new URLSearchParams('status=published');
    mockLists([published]);
    render(<CoursesPage />);

    expect(await screen.findByRole('heading', { name: published.title })).toBeInTheDocument();
    expect(screen.getByLabelText('Статус')).toHaveValue('published');
    expect(apiMock.get).toHaveBeenCalledWith(expect.stringContaining('/v1/courses?status=published'));

    fireEvent.change(screen.getByLabelText('Статус'), { target: { value: 'draft' } });
    expect(navigation.push).toHaveBeenCalledWith('/courses?status=draft', { scroll: false });
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.delete).not.toHaveBeenCalled();
  });

  it('puts visible compact owned cards before a closed blueprint disclosure', async () => {
    const { container } = render(<CoursesPage />);
    expect(await screen.findByRole('heading', { name: draft.title })).toBeInTheDocument();
    expect(container.querySelector('[data-catalog-layout="workspace-v1"]')).toBeInTheDocument();
    const list = results(container);
    const card = list.querySelector<HTMLElement>('article[data-course-card]')!;
    const templates = container.querySelector<HTMLDetailsElement>('details[data-blueprint-catalog]')!;
    expect(list.compareDocumentPosition(templates) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(templates.open).toBe(false);
    expect(card).toHaveClass('bg-card', 'p-5');
    expect(card.style.opacity).toBe('');
    expect(card.outerHTML).not.toMatch(/bg-gradient|animate-fade-up|animation-delay|h-28|truncate/);
    expect(within(card).getByRole('link', { name: draft.title })).toHaveAttribute('href', '/courses/draft-1');
    expect(screen.getByText('В текущем списке:', { exact: false })).toHaveTextContent('В текущем списке: 1');
    expect(screen.getByRole('heading', { level: 1, name: 'Курсы' })).toBeInTheDocument();
    expect(screen.getByRole('searchbox', { name: 'Поиск' })).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.delete).not.toHaveBeenCalled();

    fireEvent.click(templates.querySelector('summary')!);
    expect(templates.open).toBe(true);
    expect(within(templates).getByRole('link', { name: ru.courses.blueprint.open })).toHaveAttribute('href', '/courses/templates/kz-finance-information-security');
  });

  it('declares content-width-aware cards and wrapping action groups for narrow workspace columns', async () => {
    mockLists([published]);
    const { container } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: published.title });
    const card = results(container).querySelector<HTMLElement>('[data-course-card]')!;
    expect(card.closest('[data-methodologist-records]')).toHaveClass('methodologist-split');
    expect(card.parentElement).not.toHaveClass('md:grid-cols-2', 'xl:grid-cols-3');

    const edit = within(card).getByRole('link', { name: ru.common.edit });
    const unpublish = within(card).getByRole('button', { name: ru.courses.unpublish });
    const actionRow = edit.parentElement!;
    const publicationGroup = unpublish.parentElement!;
    expect(actionRow).toHaveClass('flex', 'flex-wrap', 'gap-2');
    expect(edit).toHaveClass('[flex:1_1_7rem]', 'min-h-11');
    expect(publicationGroup.parentElement).toBe(actionRow);
    expect(publicationGroup).toHaveClass('[flex:1_1_10rem]', 'grid-cols-[minmax(0,1fr)_44px]');
    expect(unpublish).toHaveClass('min-h-11');
    expect(publicationGroup.querySelector('summary')).toHaveClass('min-h-11', 'min-w-11');
    expect(edit).toHaveAttribute('href', '/courses/published-1/edit');
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('shows real delivery, AI, review and blueprint flags with their existing next actions', async () => {
    mockLists([
      published,
      { ...draft, id: 'ai-1', title: 'AI draft', ai_generated: true, review_status: 'pending' },
      { ...draft, id: 'scorm-1', title: 'SCORM course', delivery_type: 'scorm' },
      { ...draft, id: 'blueprint-1', title: 'Адаптируемый курс', source_analysis: { blueprint: { id: blueprint.id } } },
    ]);
    const { container } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: published.title });
    const list = within(results(container));
    expect(list.getByRole('link', { name: ru.authenticatedUi.course.assignEmployees })).toHaveAttribute('href', '/assignments?course_id=published-1');
    fireEvent.click(list.getByRole('button', { name: /AI draft/ }));
    expect(list.getByText('AI')).toBeInTheDocument();
    expect(list.getByText(ru.courses.reviewRequired)).toBeInTheDocument();
    expect(list.getByRole('link', { name: ru.courses.reviewCourse })).toHaveAttribute('href', '/courses/ai-1/edit');
    fireEvent.click(list.getByRole('button', { name: /SCORM course/ }));
    expect(within(list.getByRole('region')).getByText('SCORM')).toBeInTheDocument();
    fireEvent.click(list.getByRole('button', { name: /Адаптируемый курс/ }));
    expect(list.getByText(ru.courses.reviewRequired)).toBeInTheDocument();
    expect(list.getByRole('link', { name: ru.courses.blueprint.open })).toHaveAttribute('href', `/courses/templates/${blueprint.id}?course_id=blueprint-1`);
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('distinguishes loading, load failure, retry and an actually empty catalogue', async () => {
    const pending = deferred<{ data: unknown[] }>();
    apiMock.get.mockImplementation((url: string) => url.startsWith('/v1/courses?') ? pending.promise : Promise.resolve({ data: [] }));
    const { container } = render(<CoursesPage />);
    expect(results(container)).toHaveAttribute('aria-busy', 'true');
    expect(within(results(container)).getByRole('status')).toHaveTextContent(ru.common.loading);
    expect(screen.queryByText(ru.courses.noCourses)).not.toBeInTheDocument();
    await act(async () => pending.reject(new Error('Catalogue unavailable')));
    expect(within(results(container)).getByRole('alert')).toHaveTextContent('Catalogue unavailable');
    expect(screen.queryByText(ru.courses.noCourses)).not.toBeInTheDocument();
    mockLists([]);
    fireEvent.click(within(results(container)).getByRole('button', { name: ru.common.retry }));
    expect(await screen.findByRole('heading', { name: ru.courses.noCourses })).toBeInTheDocument();
    expect(screen.getByText(courseCatalogCopy.ru.emptyHint)).toBeInTheDocument();
    expect(results(container)).toHaveAttribute('aria-busy', 'false');
  });

  it('distinguishes filtered-empty and resets both existing API query parameters', async () => {
    apiMock.get.mockImplementation((url: string) => Promise.resolve({ data: url.startsWith('/v1/courses?') && !url.includes('q=') && !url.includes('status=') ? [draft] : [] }));
    render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск' }), { target: { value: 'не найдено' } });
    fireEvent.change(screen.getByLabelText(ru.courses.status), { target: { value: 'published' } });
    expect(await screen.findByRole('heading', { name: courseCatalogCopy.ru.filteredEmpty })).toBeInTheDocument();
    expect(screen.queryByText(ru.courses.noCourses)).not.toBeInTheDocument();
    const queryUrl = apiMock.get.mock.calls.map(([url]) => url).find((url: string) => url.includes('q=') && url.includes('status='));
    expect(new URLSearchParams(queryUrl.split('?')[1]).get('q')).toBe('не найдено');
    expect(new URLSearchParams(queryUrl.split('?')[1]).get('status')).toBe('published');
    fireEvent.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
    expect(await screen.findByRole('heading', { name: draft.title })).toBeInTheDocument();
    expect(screen.getByRole('searchbox', { name: 'Поиск' })).toHaveValue('');
    expect(screen.getByLabelText(ru.courses.status)).toHaveValue('');
    expect(apiMock.get).toHaveBeenLastCalledWith('/v1/courses?per_page=100');
  });

  it.each(['success', 'error'])('does not restore an obsolete query %s after the current list loads', async (outcome) => {
    const oldRead = deferred<{ data: unknown[] }>();
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/courses?per_page=100') return oldRead.promise;
      return Promise.resolve({ data: url.startsWith('/v1/courses?') ? [{ ...draft, id: 'current', title: 'Current query' }] : [] });
    });
    const { container } = render(<CoursesPage />);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск' }), { target: { value: 'current' } });
    await screen.findByRole('heading', { name: 'Current query' });
    await act(async () => {
      if (outcome === 'success') oldRead.resolve({ data: [draft] });
      else oldRead.reject(new Error('Obsolete error'));
    });
    expect(within(results(container)).getByRole('heading', { name: 'Current query' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: draft.title })).not.toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('removes settled old cards and actions immediately when a new query is pending', async () => {
    const nextRead = deferred<{ data: unknown[] }>();
    const { container } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    apiMock.get.mockReturnValue(nextRead.promise);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск' }), { target: { value: 'next' } });
    expect(results(container)).toHaveAttribute('aria-busy', 'true');
    expect(results(container).querySelector('[data-course-card]')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.courses.publish })).not.toBeInTheDocument();
    await act(async () => nextRead.resolve({ data: [] }));
  });

  it.each(['user', 'tenant', 'role', 'session'])('isolates delayed reads and open creation on a %s transition', async (transition) => {
    const oldRead = deferred<{ data: unknown[] }>();
    apiMock.get.mockImplementation((url: string) => url === '/v1/courses?per_page=100' ? oldRead.promise : Promise.resolve({ data: [] }));
    const { rerender, container } = render(<CoursesPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Создать вручную' }));
    fireEvent.change(screen.getByLabelText(ru.courses.courseTitle), { target: { value: 'Old actor form' } });
    if (transition === 'user') context.user!.user_id = 'author-2';
    if (transition === 'tenant') context.user!.tenant_id = 'tenant-2';
    if (transition === 'role') context.user!.role = 'admin';
    if (transition === 'session') context.epoch += 1;
    mockLists([{ ...draft, id: 'new-actor', title: 'Current actor' }]);
    rerender(<CoursesPage />);
    await screen.findByRole('heading', { name: 'Current actor' });
    expect(screen.queryByDisplayValue('Old actor form')).not.toBeInTheDocument();
    await act(async () => oldRead.resolve({ data: [draft] }));
    expect(within(results(container)).getByRole('heading', { name: 'Current actor' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: draft.title })).not.toBeInTheDocument();
    if (transition === 'role') {
      expect(screen.queryByRole('button', { name: /Создать курс/ })).not.toBeInTheDocument();
      expect(container.querySelector('[data-blueprint-catalog]')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: ru.courses.publish })).not.toBeInTheDocument();
    }
  });

  it('rejects a delayed confirmation after actor switch without deleting', async () => {
    const confirmation = deferred<boolean>();
    confirmMock.mockReturnValue(confirmation.promise);
    const { rerender, container } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    fireEvent.click(results(container).querySelector('summary')!);
    fireEvent.click(screen.getByRole('button', { name: ru.dialogs.delete }));
    context.epoch += 1;
    rerender(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    await act(async () => confirmation.resolve(true));
    expect(apiMock.delete).not.toHaveBeenCalled();
  });

  it.each(['success', 'error'])('ignores an obsolete mutation %s continuation after actor switch', async (outcome) => {
    const mutation = deferred<{ data: unknown }>();
    apiMock.post.mockReturnValue(mutation.promise);
    const { rerender } = render(<CoursesPage />);
    fireEvent.click(await screen.findByRole('button', { name: ru.courses.publish }));
    context.epoch += 1;
    mockLists([]);
    rerender(<CoursesPage />);
    await screen.findByRole('heading', { name: ru.courses.noCourses });
    const reads = apiMock.get.mock.calls.length;
    await act(async () => {
      if (outcome === 'success') mutation.resolve({ data: {} });
      else mutation.reject(new Error('Old mutation failed'));
    });
    expect(apiMock.get).toHaveBeenCalledTimes(reads);
    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('creates a manual course on explicit action and keeps new SCORM imports unavailable', async () => {
    apiMock.post.mockResolvedValue({ data: {} });
    render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    expect(screen.getByRole('link', { name: 'Задания генерации' })).toHaveAttribute('href', '/ai/generate');
    fireEvent.click(screen.getByRole('button', { name: 'Создать вручную' }));
    fireEvent.change(screen.getByLabelText(ru.courses.courseTitle), { target: { value: 'Manual title' } });
    fireEvent.change(screen.getByLabelText(ru.courses.courseDescription), { target: { value: 'Description' } });
    expect(screen.getByRole('link', { name: 'Создать из документов' })).toHaveAttribute('href', '/ai/generate?new=1');
    expect(apiMock.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: ru.common.create }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/courses', { title: 'Manual title', description: 'Description' }));
    await waitFor(() => expect(screen.queryByLabelText(ru.courses.courseTitle)).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: ru.courses.importScorm })).not.toBeInTheDocument();
    expect(apiMock.post).toHaveBeenCalledTimes(1);
  });

  it('retains explicit unpublish and draft delete actions separately from archive', async () => {
    mockLists([published, draft]);
    apiMock.post.mockResolvedValue({ data: {} });
    apiMock.delete.mockResolvedValue({ data: {} });
    confirmMock.mockResolvedValue(true);
    const { container } = render(<CoursesPage />);
    fireEvent.click(await screen.findByRole('button', { name: ru.courses.unpublish }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/courses/published-1/unpublish'));
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(draft.title) }));
    const card = within(results(container)).getByRole('heading', { name: draft.title }).closest('article')!;
    fireEvent.click(card.querySelector('summary')!);
    fireEvent.click(within(card).getByRole('button', { name: ru.dialogs.delete }));
    await waitFor(() => expect(apiMock.delete).toHaveBeenCalledWith('/v1/courses/draft-1'));
    expect(apiMock.post).not.toHaveBeenCalledWith('/v1/courses/draft-1/archive');
  });

  it('keeps blueprint failure and retry secondary without hiding owned courses', async () => {
    apiMock.get.mockImplementation((url: string) => url.startsWith('/v1/course-blueprints?') ? Promise.reject(new Error('Blueprint unavailable')) : Promise.resolve({ data: [draft] }));
    const { container } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    const templates = container.querySelector<HTMLDetailsElement>('[data-blueprint-catalog]')!;
    fireEvent.click(templates.querySelector('summary')!);
    expect(within(templates).getByRole('alert')).toHaveTextContent('Blueprint unavailable');
    mockLists();
    fireEvent.click(within(templates).getByRole('button', { name: ru.common.retry }));
    expect(await within(templates).findByRole('heading', { name: blueprint.title })).toBeInTheDocument();
    expect(within(results(container)).getByRole('heading', { name: draft.title })).toBeInTheDocument();
  });

  it('rejects obsolete blueprint locale responses', async () => {
    const oldBlueprint = deferred<{ data: unknown[] }>();
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/course-blueprints?locale=ru') return oldBlueprint.promise;
      if (url === '/v1/course-blueprints?locale=kk') return Promise.resolve({ data: [{ ...blueprint, title: 'Қазақша негіз' }] });
      return Promise.resolve({ data: [draft] });
    });
    const { container, rerender } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    context.lang = 'kk';
    rerender(<CoursesPage />);
    const templates = container.querySelector<HTMLDetailsElement>('[data-blueprint-catalog]')!;
    fireEvent.click(templates.querySelector('summary')!);
    await within(templates).findByRole('heading', { name: 'Қазақша негіз' });
    await act(async () => oldBlueprint.resolve({ data: [blueprint] }));
    expect(within(templates).getByRole('heading', { name: 'Қазақша негіз' })).toBeInTheDocument();
    expect(within(templates).queryByRole('heading', { name: blueprint.title })).not.toBeInTheDocument();
  });

  it.each(['ru', 'kk', 'en'] as const)('renders feature-owned %s copy without shared locale changes', async (locale) => {
    context.lang = locale;
    mockLists([]);
    render(<CoursesPage />);
    expect(await screen.findByText(courseCatalogCopy[locale].emptyHint)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: courseCatalogCopy[locale].ownCourses })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'none' } });
    expect(await screen.findByRole('heading', { name: courseCatalogCopy[locale].filteredEmpty })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: courseCatalogCopy[locale].resetFilters })).toBeInTheDocument();
    expect(Object.keys(courseCatalogCopy[locale]).sort()).toEqual(Object.keys(courseCatalogCopy.ru).sort());
  });

  it('does not request or retain catalogue data after logout', async () => {
    const { rerender, container } = render(<CoursesPage />);
    await screen.findByRole('heading', { name: draft.title });
    context.user = null;
    rerender(<CoursesPage />);
    const reads = apiMock.get.mock.calls.length;
    expect(container).toBeEmptyDOMElement();
    expect(apiMock.get).toHaveBeenCalledTimes(reads);
  });
});
