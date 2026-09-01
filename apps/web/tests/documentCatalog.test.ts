import {
  documentDeleteError,
  getDuplicateDocumentConflict,
  isDocumentSelectable,
  type DocumentCatalogItem,
} from '@/lib/documentCatalog';
import { describe, expect, it } from 'vitest';

const document = (status: DocumentCatalogItem['index']['status']): DocumentCatalogItem => ({
  id: 'document-1',
  source_family_id: 'document-1',
  title: 'Source',
  filename: 'source.md',
  content_type: 'text/markdown',
  size: 100,
  description: '',
  category: 'general',
  index: {
    status,
    error_code: null,
    message: null,
    chunks_total: 1,
    chunks_indexed: 1,
    indexed_at: null,
    revision: 1,
  },
  version: 1,
  is_latest: true,
  lifecycle_status: 'active',
  deletion_error_code: null,
  deletion_error_message: null,
  deletion_job_id: null,
  created_by: 'Иван Петров',
  created_at: '2026-07-24T00:00:00Z',
  updated_at: '2026-07-24T00:00:00Z',
});

describe('document catalog UI contract', () => {
  it('allows ready and partial active sources in AI generation', () => {
    expect(isDocumentSelectable(document('ready'))).toBe(true);
    expect(isDocumentSelectable(document('partial'))).toBe(true);
    expect(isDocumentSelectable(document('processing'))).toBe(false);
    expect(isDocumentSelectable(document('failed'))).toBe(false);
  });

  it('rejects a tombstoned source even if its index is ready', () => {
    const pending = document('ready');
    pending.lifecycle_status = 'deletion_pending';

    expect(isDocumentSelectable(pending)).toBe(false);
  });

  it('formats the structured in-use deletion error', () => {
    const error = {
      response: {
        data: {
          details: {
            code: 'document_in_use',
            summary: { total: 3 },
          },
        },
      },
    };

    expect(documentDeleteError(error)).toContain('3');
    expect(documentDeleteError(error)).toContain('Сначала отвяжите');
  });

  it('recognizes an exact-file conflict returned by the upload API', () => {
    expect(getDuplicateDocumentConflict({
      response: {
        data: {
          detail: {
            code: 'duplicate_document',
            existing: {
              id: 'document-1',
              title: 'Правила ИБ',
              filename: 'rules.pdf',
              version: 2,
            },
          },
        },
      },
    })).toEqual({
      id: 'document-1',
      title: 'Правила ИБ',
      filename: 'rules.pdf',
      version: 2,
    });
  });
});
