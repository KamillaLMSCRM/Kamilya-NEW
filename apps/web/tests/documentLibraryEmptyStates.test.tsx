import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DocumentsPage from '@/app/documents/page';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { role: 'methodologist' } }) }));
vi.mock('@/features/source-actuality/SourceActualityPanel', () => ({ SourceActualityPanel: () => null }));

beforeEach(() => {
  vi.resetAllMocks();
  useLanguageStore.setState({ lang: 'ru' });
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/v1/documents/catalog')
    ? { items: [], page: { next_cursor: null, has_more: false } }
    : { enabled: false } }) as never);
});

afterEach(() => {
  vi.useRealTimers();
});

const staleOcrDocument = {
  id: 'qa-stale-ocr', source_family_id: 'qa-stale-ocr-family', title: 'Synthetic scanned policy',
  filename: 'synthetic-policy.pdf', content_type: 'application/pdf', size: 1024,
  description: '', category: 'general', version: 1, is_latest: true,
  lifecycle_status: 'active', created_at: '2026-10-17T07:00:00Z', updated_at: '2026-10-17T07:00:00Z',
  index: { status: 'failed', error_code: 'ocr_required', message: 'old OCR error', chunks_total: 0, chunks_indexed: 0, indexed_at: null, revision: 1 },
  usages_summary: { total: 0, courses: 0, positions: 0, lessons: 0, active_jobs: 0 },
};

const catalogWith = (document = staleOcrDocument) => ({
  items: [document], page: { next_cursor: null, has_more: false },
});

describe('document library empty-state intent', () => {
  it('does not project a previous OCR error onto queued, running, or completed reindex jobs', async () => {
    vi.useFakeTimers();
    const jobs = [
      { status: 'running', stage: 'indexing', progress: 25, message: 'Индексация', errors: [], timestamps: {} },
      { status: 'completed', stage: 'completed', progress: 100, message: 'Готово', errors: [], timestamps: {} },
    ];
    vi.mocked(api.get).mockImplementation(async (url) => {
      const text = String(url);
      if (text.startsWith('/v1/documents/catalog')) return { data: catalogWith() } as never;
      if (text.includes('/v1/ai/jobs/qa-stale-job')) return { data: jobs.shift() ?? { status: 'completed', stage: 'completed', progress: 100, message: 'Готово', errors: [], timestamps: {} } } as never;
      return { data: { enabled: false } } as never;
    });
    vi.mocked(api.post).mockResolvedValue({ data: { job_id: 'qa-stale-job', revision: 2 } } as never);

    render(<DocumentsPage />);
    await vi.runAllTicks();
    await vi.advanceTimersByTimeAsync(0);
    await vi.runAllTicks();
    fireEvent.click(screen.getByRole('button', { name: 'Переиндексировать: Synthetic scanned policy' }));
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(screen.queryByText(/Документ состоит из сканированных страниц/)).not.toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(5_000);
    expect(screen.getByText('Выполняется')).toBeInTheDocument();
    expect(screen.queryByText(/Документ состоит из сканированных страниц/)).not.toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(5_000);
    expect(screen.getByText('Завершено')).toBeInTheDocument();
    expect(screen.queryByText(/Документ состоит из сканированных страниц/)).not.toBeInTheDocument();
  });

  it('still shows the OCR hint when the current failed job reports OCR required', async () => {
    vi.useFakeTimers();
    vi.mocked(api.get).mockImplementation(async (url) => {
      const text = String(url);
      if (text.startsWith('/v1/documents/catalog')) return { data: catalogWith() } as never;
      if (text.includes('/v1/ai/jobs/qa-failed-job')) return { data: {
        status: 'failed', stage: 'failed', progress: 12, message: 'OCR unavailable now',
        errors: [{ code: 'ocr_required', message: 'OCR required' }], timestamps: {},
      } } as never;
      return { data: { enabled: false } } as never;
    });
    vi.mocked(api.post).mockResolvedValue({ data: { job_id: 'qa-failed-job', revision: 2 } } as never);

    render(<DocumentsPage />);
    await vi.runAllTicks();
    await vi.advanceTimersByTimeAsync(0);
    await vi.runAllTicks();
    fireEvent.click(screen.getByRole('button', { name: 'Переиндексировать: Synthetic scanned policy' }));
    await vi.advanceTimersByTimeAsync(5_000);
    expect(screen.getByText(/Документ состоит из сканированных страниц/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
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
