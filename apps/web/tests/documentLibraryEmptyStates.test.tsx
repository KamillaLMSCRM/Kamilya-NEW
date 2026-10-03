import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DocumentsPage from '@/app/documents/page';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { role: 'methodologist' } }) }));
vi.mock('@/components/ui/ConfirmDialog', () => ({ useConfirm: () => ({ confirm: vi.fn(), dialog: null }) }));
vi.mock('@/features/source-actuality/SourceActualityPanel', () => ({ SourceActualityPanel: () => null }));

beforeEach(() => {
  vi.resetAllMocks();
  useLanguageStore.setState({ lang: 'ru' });
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/v1/documents/catalog')
    ? { items: [], page: { next_cursor: null, has_more: false } }
    : { enabled: false } }) as never);
});

describe('document library empty-state intent', () => {
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
