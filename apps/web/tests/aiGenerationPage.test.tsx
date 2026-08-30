import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AIGeneratePage from '@/app/ai/generate/page';
import { api } from '@/lib/api';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

const apiMock = vi.mocked(api);
const activeJob = {
  id: 'job-1', status: 'running', course_id: 'course-1', created_at: '2026-08-07T08:00:00Z',
  updated_at: new Date().toISOString(), progress: 35, stage: 'content_generation', message: '',
  queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: null, tenant_active_limit: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  localStorage.setItem('ai_active_job_id', activeJob.id);
  apiMock.get.mockImplementation(async (url: string) => {
    if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
    if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: activeJob } as any;
    throw new Error(`Unexpected GET ${url}`);
  });
  apiMock.post.mockResolvedValue({ data: {} } as any);
});

describe('/ai/generate job workflow parity', () => {
  it('restores an active job and returns to the documents view after cancellation', async () => {
    render(<AIGeneratePage />);

    expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/jobs/job-1/cancel'));
    await waitFor(() => expect(screen.queryByText('Прогресс генерации')).not.toBeInTheDocument());
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
    expect(screen.getByText(/Перетащите документы/)).toBeInTheDocument();
  });

  it('shows the existing document instead of a generic upload failure for an exact duplicate', async () => {
    localStorage.clear();
    apiMock.post.mockRejectedValueOnce({
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
    });

    const { container } = render(<AIGeneratePage />);
    await screen.findByText(/Перетащите документы/);
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: { files: [new File(['same file'], 'renamed-rules.pdf', { type: 'application/pdf' })] },
    });

    expect(await screen.findByText('Этот файл уже есть в библиотеке: «Правила ИБ», версия 2.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Открыть существующий документ' })).toBeInTheDocument();
  });

  it('returns a restored failed job to the document form without submitting automatically', async () => {
    localStorage.clear();
    const failedJob = {
      ...activeJob,
      id: 'failed-job',
      job_type: 'course_generation',
      course_id: null,
      status: 'failed',
      stage: 'failed',
      message: 'SoftTimeLimitExceeded: generation failed',
    };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === '/v1/ai/jobs') return { data: [failedJob] } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);

    expect(await screen.findByText('SoftTimeLimitExceeded: generation failed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));

    expect(await screen.findByText(/Перетащите документы/)).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalledWith('/v1/ai/generate-course', expect.anything());
  });
});

const readyDocuments = [
  {
    id: 'doc-1', title: 'Правила ИБ', filename: 'a.pdf', content_type: 'application/pdf',
    size: 10, description: '',
    index: { status: 'ready', error_code: null, message: null, chunks_total: 1, chunks_indexed: 1, indexed_at: null, revision: 1 },
  },
  {
    id: 'doc-2', title: 'Охрана труда', filename: 'b.pdf', content_type: 'application/pdf',
    size: 10, description: '',
    index: { status: 'ready', error_code: null, message: null, chunks_total: 1, chunks_indexed: 1, indexed_at: null, revision: 1 },
  },
  {
    id: 'doc-3', title: 'Сломанный документ', filename: 'c.pdf', content_type: 'application/pdf',
    size: 10, description: '',
    index: { status: 'failed', error_code: 'conversion_failed', message: 'Ошибка', chunks_total: null, chunks_indexed: null, indexed_at: null, revision: 1 },
  },
] as any;

function mockCatalogWith(items: any[]) {
  localStorage.clear();
  apiMock.get.mockImplementation(async (url: string) => {
    if (url.startsWith('/v1/documents/catalog')) return { data: { items, page: { has_more: false } } } as any;
    throw new Error(`Unexpected GET ${url}`);
  });
}

describe('/ai/generate multi-document selection contract', () => {
  it('uses an automatic course format and keeps module count as an advanced override', async () => {
    mockCatalogWith(readyDocuments);
    render(<AIGeneratePage />);
    expect(await screen.findByRole('combobox', { name: 'Формат курса' })).toHaveValue('automatic');
    expect(screen.queryByRole('spinbutton', { name: 'Количество модулей' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Расширенные настройки структуры'));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Задать количество модулей вручную' }));
    expect(screen.getByRole('spinbutton', { name: 'Количество модулей' })).toBeInTheDocument();
  });

  it('keeps not-ready documents disabled with a visible reason', async () => {
    mockCatalogWith(readyDocuments);
    render(<AIGeneratePage />);

    const broken = await screen.findByRole('checkbox', { name: /Сломанный документ/ });
    expect(broken).toBeDisabled();
    expect(screen.getAllByText('Ошибка').length).toBeGreaterThan(0);
  });

  it('submits selected document ids in selection order and shows the selected count', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockResolvedValue({ data: activeJob } as any);
    render(<AIGeneratePage />);

    const first = await screen.findByRole('checkbox', { name: /Правила ИБ/ });
    const second = screen.getByRole('checkbox', { name: /Охрана труда/ });
    fireEvent.click(second);
    fireEvent.click(first);

    expect(await screen.findByText(/Загруженные документы/)).toHaveTextContent('2 документа');

    fireEvent.click(await screen.findByRole('button', { name: /Генерировать курс/ }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalled());
    const [, payload] = apiMock.post.mock.calls[0];
    expect((payload as any).documents).toEqual(['doc-2', 'doc-1']);
  });

  it('blocks selection beyond five documents', async () => {
    const many = Array.from({ length: 7 }, (_, i) => ({
      id: `doc-${i + 1}`, title: `Документ ${i + 1}`, filename: `f${i}.pdf`,
      content_type: 'application/pdf', size: 10, description: '',
      index: { status: 'ready', error_code: null, message: null, chunks_total: 1, chunks_indexed: 1, indexed_at: null, revision: 1 },
    }));
    mockCatalogWith(many);
    apiMock.post.mockResolvedValue({ data: activeJob } as any);
    render(<AIGeneratePage />);

    await screen.findByText(/Загруженные документы/);
    for (let i = 1; i <= 7; i++) {
      const box = screen.getByRole('checkbox', { name: new RegExp(`Выбрать документ Документ ${i}`) });
      fireEvent.click(box);
    }

    expect(await screen.findByText(/Загруженные документы/)).toHaveTextContent('5 документов');
  });

  it('requires explicit confirmation before generating from mixed-language sources', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockImplementation(async (url: string, payload?: any) => {
      if (url === '/v1/ai/document-compatibility') {
        return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      }
      if (url === '/v1/ai/generate-course' && payload?.language_confirmed !== true) {
        throw {
          response: {
            status: 409,
            data: {
              detail: {
                code: 'mixed_language_sources',
                message: 'Selected documents use different languages',
                detected_languages: ['kk', 'ru'],
              },
            },
          },
        };
      }
      if (url === '/v1/ai/generate-course') return { data: activeJob } as any;
      throw new Error(`Unexpected POST ${url}`);
    });
    render(<AIGeneratePage />);

    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Охрана труда/ }));
    // The generate button stays inert until the debounced compatibility check resolves.
    await screen.findByText('Документы образуют одну тематическую группу. Можно проектировать единый курс.');
    fireEvent.click(await screen.findByRole('button', { name: /Генерировать курс/ }));

    const dialog = await screen.findByRole('dialog', { name: 'Документы на разных языках' });
    expect(dialog).toHaveTextContent('Казахский');
    expect(dialog).toHaveTextContent('Русский');
    expect(dialog).toHaveTextContent('Язык будущего курса: Русский');
    expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/generate-course', expect.objectContaining({ language_confirmed: false }));

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить и запустить' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/ai/generate-course',
      expect.objectContaining({ language_confirmed: true }),
    ));
    expect(screen.queryByRole('dialog', { name: 'Документы на разных языках' })).not.toBeInTheDocument();
  });
});

describe('/ai/generate combined 409 acknowledgement sequences', () => {
  async function selectTwoDocumentsAndClickGenerate() {
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Охрана труда/ }));
    // The generate button stays inert until the debounced compatibility check resolves.
    await screen.findByText('Документы образуют одну тематическую группу. Можно проектировать единый курс.');
    fireEvent.click(await screen.findByRole('button', { name: /Генерировать курс/ }));
  }

  it('keeps language confirmation through the reuse dialog when sources are mixed-language and already used', async () => {
    mockCatalogWith(readyDocuments);
    let generateCalls = 0;
    apiMock.post.mockImplementation(async (url: string, payload?: any) => {
      if (url === '/v1/ai/document-compatibility') {
        return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      }
      if (url === '/v1/ai/generate-course') {
        generateCalls += 1;
        if (payload?.language_confirmed !== true) {
          throw {
            response: {
              status: 409,
              data: {
                detail: {
                  code: 'mixed_language_sources',
                  message: 'Selected documents use different languages',
                  detected_languages: ['kk', 'ru'],
                },
              },
            },
          };
        }
        if (!payload?.reuse_reason) {
          throw {
            response: {
              status: 409,
              data: {
                detail: {
                  code: 'source_documents_already_used',
                  message: 'These documents already have courses',
                  existing_courses: [{ id: 'course-9', title: 'Существующий курс', status: 'draft' }],
                },
              },
            },
          };
        }
        return { data: activeJob } as any;
      }
      throw new Error(`Unexpected POST ${url}`);
    });

    await selectTwoDocumentsAndClickGenerate();

    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить и запустить' }));
    const reuseDialog = await screen.findByRole('dialog', { name: 'Источник уже использован' });
    expect(reuseDialog).toBeInTheDocument();
    expect(generateCalls).toBe(2);

    fireEvent.click(screen.getByLabelText('Другой язык'));
    fireEvent.click(screen.getByRole('button', { name: 'Создать независимый курс' }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/ai/generate-course',
      expect.objectContaining({ language_confirmed: true, reuse_reason: 'different_language' }),
    ));
    expect(generateCalls).toBe(3);
    expect(screen.queryByRole('dialog', { name: 'Документы на разных языках' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Источник уже использован' })).not.toBeInTheDocument();
  });

  it('keeps the reuse reason through the language dialog when reuse is acknowledged first', async () => {
    mockCatalogWith(readyDocuments);
    let generateCalls = 0;
    apiMock.post.mockImplementation(async (url: string, payload?: any) => {
      if (url === '/v1/ai/document-compatibility') {
        return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      }
      if (url === '/v1/ai/generate-course') {
        generateCalls += 1;
        if (!payload?.reuse_reason) {
          throw {
            response: {
              status: 409,
              data: {
                detail: {
                  code: 'source_documents_already_used',
                  message: 'These documents already have courses',
                  existing_courses: [{ id: 'course-9', title: 'Существующий курс', status: 'draft' }],
                },
              },
            },
          };
        }
        if (payload?.language_confirmed !== true) {
          throw {
            response: {
              status: 409,
              data: {
                detail: {
                  code: 'mixed_language_sources',
                  message: 'Selected documents use different languages',
                  detected_languages: ['kk', 'ru'],
                },
              },
            },
          };
        }
        return { data: activeJob } as any;
      }
      throw new Error(`Unexpected POST ${url}`);
    });

    await selectTwoDocumentsAndClickGenerate();

    fireEvent.click(await screen.findByLabelText('Другой язык'));
    fireEvent.click(screen.getByRole('button', { name: 'Создать независимый курс' }));
    const languageDialog = await screen.findByRole('dialog', { name: 'Документы на разных языках' });
    expect(languageDialog).toBeInTheDocument();
    expect(generateCalls).toBe(2);

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить и запустить' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/ai/generate-course',
      expect.objectContaining({ language_confirmed: true, reuse_reason: 'different_language' }),
    ));
    expect(generateCalls).toBe(3);
    expect(screen.queryByRole('dialog', { name: 'Источник уже использован' })).not.toBeInTheDocument();
  });
});
