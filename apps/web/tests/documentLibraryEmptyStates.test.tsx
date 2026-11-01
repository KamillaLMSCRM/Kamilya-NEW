import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DocumentsPage from '@/app/documents/page';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';
const auth = vi.hoisted(() => ({ user: { user_id: 'author-a', tenant_id: 'tenant-a', role: 'methodologist' }, accessToken: 'token-a' }));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select(auth) }));
vi.mock('@/features/source-actuality/SourceActualityPanel', () => ({ SourceActualityPanel: () => null }));

beforeEach(() => {
  vi.resetAllMocks();
  auth.user = { user_id: 'author-a', tenant_id: 'tenant-a', role: 'methodologist' };
  auth.accessToken = 'token-a';
  useLanguageStore.setState({ lang: 'ru' });
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/v1/documents/catalog')
    ? { items: [], page: { next_cursor: null, has_more: false } }
    : { enabled: false } }) as never);
});

describe('document library empty-state intent', () => {
  it('does not retain another actor catalog or finish its source download', async () => {
    let resolve!: (value: { data: Blob }) => void;
    vi.mocked(api.get).mockImplementation((url) => {
      if (String(url).endsWith('/download')) return new Promise((done) => { resolve = done; }) as never;
      return Promise.resolve({ data: String(url).startsWith('/v1/documents/catalog')
        ? { items: auth.user.user_id !== 'author-a' ? [] : [{ id: 'doc-actor-a', title: 'Actor A source', filename: 'source.pdf', content_type: 'application/pdf', size: 128, version: 1, category: 'general', lifecycle_status: 'active', index: { status: 'ready', chunks_total: 1, chunks_indexed: 1, revision: 1 } }], page: { next_cursor: null, has_more: false } }
        : { enabled: false } }) as never;
    });
    const createUrl = vi.fn().mockReturnValue('blob:old-source');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const view = render(<DocumentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Actor A source' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Исходный файл' }));
    auth.user = { user_id: 'author-b', tenant_id: 'tenant-b', role: 'methodologist' };
    auth.accessToken = 'token-b';
    view.rerender(<DocumentsPage />);
    await act(async () => resolve({ data: new Blob(['old-source']) }));
    expect(screen.queryByRole('button', { name: 'Actor A source' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(createUrl).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
  });
  it('updates an open inspection from the latest catalog instead of retaining its old processing snapshot', async () => {
    let ready = false;
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/v1/documents/catalog')
      ? { items: [{ id: 'doc-1', source_family_id: 'family-1', title: 'Source under inspection', filename: 'source.pdf',
        content_type: 'application/pdf', size: 128, description: '', category: 'general', version: 1, is_latest: true,
        lifecycle_status: 'active', created_at: '', updated_at: '',
        index: { status: ready ? 'ready' : 'processing', error_code: null, message: null, chunks_total: 2, chunks_indexed: ready ? 2 : 0, indexed_at: null, revision: 1 },
      }], page: { next_cursor: null, has_more: false } } : { enabled: false } }) as never);
    render(<DocumentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Source under inspection' }));
    expect(within(screen.getByRole('dialog')).getByText('Обработка продолжается')).toBeInTheDocument();
    ready = true;
    vi.useFakeTimers();
    try {
      // Existing catalog polling starts before fake timers; refresh through its filter dependency instead.
      fireEvent.change(screen.getByRole('textbox', { name: 'Поиск документов' }), { target: { value: 'Source' } });
      await act(async () => { await vi.advanceTimersByTimeAsync(300); });
      expect(within(screen.getByRole('dialog')).getByText('Индекс готов')).toBeInTheDocument();
      expect(within(screen.getByRole('dialog')).getByText('Фрагменты индекса: 2 / 2')).toBeInTheDocument();
    } finally { vi.useRealTimers(); }
  });
  it('names the selected source in the real delete confirmation and cancels without a write', async () => {
    const title = 'QA BUTTONS — selected synthetic source';
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/v1/documents/catalog')
      ? { items: [{
        id: 'qa-confirm-source', source_family_id: 'qa-confirm-family', title,
        filename: 'qa-confirm.md', content_type: 'text/markdown', size: 128,
        description: '', category: 'general', version: 1, is_latest: true,
        lifecycle_status: 'active', created_at: '2026-10-17T07:00:00Z', updated_at: '2026-10-17T07:00:00Z',
        index: { status: 'ready', error_code: null, message: null, chunks_total: 1, chunks_indexed: 1, indexed_at: null, revision: 1 },
        usages_summary: { total: 0, courses: 0, positions: 0, lessons: 0, active_jobs: 0 },
      }], page: { next_cursor: null, has_more: false } }
      : { enabled: false } }) as never);
    render(<DocumentsPage />);
    fireEvent.click(await screen.findByRole('button', { name: `Удалить: ${title}` }));
    const dialog = await screen.findByRole('dialog', { name: 'Удалить документ?' });
    expect(within(dialog).getByText(title)).toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(api.delete).not.toHaveBeenCalled();
  });

  it('offers an upload hint only for an unfiltered empty active library', async () => {
    render(<DocumentsPage />);
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument();
    expect(screen.getByText('Загрузите источник, чтобы создать курс или должностную инструкцию')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Показать активные документы' })).not.toBeInTheDocument();
  });

  it.each([
    ['Требуют внимания', 'Документов с ошибкой удаления нет', 'delete_failed'],
    ['Удаляются', 'Сейчас нет документов в процессе удаления', 'deletion_pending'],
  ])('explains the empty %s lifecycle view and returns to active documents', async (tab, title, lifecycle) => {
    render(<DocumentsPage />);
    await screen.findByText('Документов пока нет');
    fireEvent.click(screen.getByRole('tab', { name: tab }));
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.queryByText('Загрузите источник, чтобы создать курс или должностную инструкцию')).not.toBeInTheDocument();
    expect(vi.mocked(api.get).mock.calls.some(([url]) => String(url).includes(`lifecycle_status=${lifecycle}`))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Показать активные документы' }));
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Активные' })).toHaveAttribute('aria-selected', 'true');
    expect(api.post).not.toHaveBeenCalled();
    expect(api.delete).not.toHaveBeenCalled();
  });

  it('distinguishes a search miss and resets both the query and catalog view', async () => {
    render(<DocumentsPage />);
    await screen.findByText('Документов пока нет');
    fireEvent.change(screen.getByRole('textbox', { name: 'Поиск документов' }), { target: { value: 'nonexistent synthetic source' } });
    expect(await screen.findByText('По выбранным фильтрам документов не найдено')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Показать активные документы' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Поиск документов' })).toHaveValue(''));
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
});
