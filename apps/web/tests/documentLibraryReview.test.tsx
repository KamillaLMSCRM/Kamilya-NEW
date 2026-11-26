import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), delete: vi.fn(), confirm: vi.fn(), search: new URLSearchParams(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => mocks.search,
}));
vi.mock('@/lib/api', () => ({ api: { get: mocks.get, delete: mocks.delete } }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector({
    user: { role: 'methodologist', user_id: 'methodologist', tenant_id: 'tenant' },
    accessToken: 'test', sessionEpoch: 1,
  }),
}));
vi.mock('@/store/languageStore', () => ({
  useLanguageStore: (selector: (state: { lang: string }) => unknown) => selector({ lang: 'ru' }),
}));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock('@/components/ui/ConfirmDialog', () => ({ useConfirm: () => ({ confirm: mocks.confirm, dialog: null }) }));
vi.mock('@/features/source-actuality/SourceActualityPanel', () => ({ SourceActualityPanel: () => null }));

import DocumentsPage from '@/app/documents/page';
import type { DocumentCatalogItem } from '@/lib/documentCatalog';

const documentId = '31fa2348-99bf-4aee-8adf-886a8dc1c5d0';
const title = 'Порядок работы с учебными материалами';
const approved: DocumentCatalogItem = {
  id: documentId, source_family_id: documentId, title, filename: 'policy.txt',
  content_type: 'text/plain', size: 1024, description: '', category: 'general',
  index: { status: 'ready', revision: 1, error_code: null, message: null, chunks_indexed: 1, chunks_total: 1, indexed_at: null },
  version: 1, is_latest: true, lifecycle_status: 'active', source_review_status: 'approved',
  deletion_error_code: null, deletion_error_message: null, deletion_job_id: null, created_by: null,
  created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z',
};
const oneUse = { total: 1, courses: 1, lessons: 0, active_jobs: 0, positions: 0 };

function catalog(items: DocumentCatalogItem[]) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url.startsWith('/v1/documents/catalog?')) return { data: { items, page: { has_more: false, next_cursor: null } } };
    if (url === '/v1/youtube/limits') return { data: { enabled: false } };
    if (url.includes('/usages?')) return { data: {
      summary: oneUse,
      items: [{ id: 'course-qa', type: 'course_source', title: 'Учебный курс', status: 'draft', route: '/courses/course-qa' }],
    } };
    throw new Error('Unexpected GET');
  });
}

describe('document library review continuation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.search = new URLSearchParams();
  });

  it('opens the exact approved source by ID and starts course creation with it selected', async () => {
    mocks.search = new URLSearchParams({ document_id: documentId });
    catalog([approved]);
    render(<DocumentsPage />);

    const create = await screen.findByRole('link', { name: 'Создать курс' });
    expect(create).toHaveAttribute('href', '/ai/generate?document_id=' + documentId);
    expect(screen.getByRole('link', { name: 'Открыть проверку' })).toHaveAttribute('href', '/documents/' + documentId + '/editorial-review');
    expect(screen.getByText('Утверждён')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Все документы' })).toHaveAttribute('href', '/documents');
    expect(mocks.get.mock.calls.some(([url]) => url.includes('include_source_review=true') && url.includes('document_id=' + documentId))).toBe(true);
  });

  it('shows an unfinished check and offers deletion of an approved source without usages', async () => {
    const other = { ...approved, id: '7b2cf8dc-5f92-41c1-b160-11b2c4c863c7', title: 'Другой документ', source_review_status: 'failed' as const };
    catalog([approved, other]);
    mocks.confirm.mockResolvedValue(true);
    mocks.delete.mockResolvedValue({ status: 202 });
    render(<DocumentsPage />);

    expect(await screen.findByText('Проверка не завершена')).toBeVisible();
    expect(screen.getAllByRole('link', { name: 'Создать курс' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Удалить: ' + title }));
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith('/v1/documents/' + documentId));
    await waitFor(() => expect(screen.queryByText(title)).not.toBeInTheDocument());
  });

  it('explains deletion blocked by a linked course without attempting to delete it', async () => {
    catalog([{ ...approved, usages_summary: oneUse }]);
    render(<DocumentsPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Удалить: ' + title }));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('link', { name: 'Открыть связанный объект: Учебный курс' })).toHaveAttribute('href', '/courses/course-qa');
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(mocks.delete).not.toHaveBeenCalled();
  });
});
