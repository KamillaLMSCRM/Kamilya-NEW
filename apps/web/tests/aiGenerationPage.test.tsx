import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AIGeneratePage from '@/app/ai/generate/page';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
const toastErrorMock = vi.hoisted(() => vi.fn());
const routerPushMock = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: routerPushMock }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: toastErrorMock, warning: vi.fn() } }));

const apiMock = vi.mocked(api);
const activeJob = {
  id: 'job-1', status: 'running', course_id: 'course-1', created_at: '2026-08-07T08:00:00Z',
  updated_at: new Date().toISOString(), progress: 35, stage: 'content_generation', message: '',
  queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: null, tenant_active_limit: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  useLanguageStore.setState({ lang: 'ru' });
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
  it('offers unknown-outcome abandonment for an already admitted active job', async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: { ...activeJob, abandon_available: true } } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    expect(screen.queryByRole('button', { name: 'Отменить' })).not.toBeInTheDocument();
    fireEvent.click((await screen.findAllByRole('button', { name: /результат неизвестен/i }))[0]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('shows a held job with read-only refresh and no resume or cancel', async () => {
    const heldJob = { ...activeJob, status: 'reconciliation_required', course_id: null,
      message: 'Сохранение требует проверки. Обратитесь к администратору.' };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: heldJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Сохранение требует проверки');
    expect(screen.queryByText('Отменить')).not.toBeInTheDocument();
    expect(screen.queryByText('Продолжить')).not.toBeInTheDocument();
    const previousReads = apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${activeJob.id}`).length;
    fireEvent.click(screen.getByRole('button', { name: 'Проверить снова' }));
    await waitFor(() => expect(apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${activeJob.id}`).length).toBeGreaterThan(previousReads));
    expect(apiMock.post).not.toHaveBeenCalled();
  });
  it('loads full lesson content before allowing an edit from a truncated preview excerpt', async () => {
    const completedJob = { ...activeJob, status: 'completed', stage: 'completed', progress: 100 };
    const fullContent = '# Полный урок\n\n' + 'Полный текст урока. '.repeat(80);
    const excerpt = `${fullContent.slice(0, 90)}...`;
    let jobReads = 0;
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) {
        jobReads += 1;
        return { data: jobReads === 1 ? activeJob : completedJob } as any;
      }
      if (url === `/v1/courses/${activeJob.course_id}/preview`) return { data: {
        source_documents: [], modules_count: 1, lessons_count: 1, quizzes_count: 0,
        modules: [{ id: 'module-1', title: 'Модуль', lessons: [{ id: 'lesson-full', title: 'Полный урок', content_preview: excerpt }] }],
      } } as any;
      if (url === `/v1/courses/${activeJob.course_id}`) return { data: { id: activeJob.course_id, title: 'Курс', description: '', review_status: 'approved', status: 'draft' } } as any;
      if (url === '/v1/lessons/lesson-full') return { data: { id: 'lesson-full', title: 'Полный урок', content: fullContent } } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    const jobInterval = vi.spyOn(window, 'setInterval');
    render(<AIGeneratePage />);
    expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
    let intervalCallback: (() => void) | undefined;
    await waitFor(() => {
      intervalCallback = jobInterval.mock.calls.find((call) => call[1] === 3000)?.[0] as (() => void) | undefined;
      expect(intervalCallback).toBeDefined();
    });
    await act(async () => {
      intervalCallback!();
      await Promise.resolve();
      await Promise.resolve();
    });
    fireEvent.click(await screen.findByRole('button', { expanded: false }));
    await screen.findByText('Полный урок');
    fireEvent.click(await screen.findByRole('button', { name: 'Редактировать' }));

    await waitFor(() => expect(document.querySelector('textarea')).toHaveValue(fullContent));
    const editor = document.querySelector('textarea');
    expect(apiMock.get).toHaveBeenCalledWith('/v1/lessons/lesson-full');
    expect(editor).toHaveValue(fullContent);
    expect(editor).not.toHaveValue(excerpt);

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(apiMock.patch).toHaveBeenCalledWith('/v1/lessons/lesson-full', {
      title: 'Полный урок', content: fullContent,
    }));
    jobInterval.mockRestore();
  });

  it.each([
    ['assessment_no_valid_questions'],
    ['assessment_coverage_incomplete'],
  ])('offers a new course without cancelling the saved assessment-review draft: %j', async (...errors) => {
    const savedDraftJob = {
      ...activeJob, status: 'interrupted', stage: 'interrupted', progress: 100,
      errors, message: 'Lessons saved; assessment requires review.',
    };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: savedDraftJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<AIGeneratePage />);

    expect(await screen.findByRole('button', { name: 'Открыть сохранённый черновик' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Создать новый курс' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Создать новый курс' }));
    expect(await screen.findByText(/Перетащите документы/)).toBeInTheDocument();
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
    expect(localStorage.getItem('ai_generation_workflow_context')).toBeNull();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('keeps assessment draft opening separate from other interrupted diagnostics', async () => {
    const savedDraftJob = {
      ...activeJob, status: 'interrupted', stage: 'interrupted', progress: 100,
      errors: ['another_diagnostic', 'assessment_no_valid_questions'], message: 'Lessons saved; assessment requires review.',
    };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: savedDraftJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<AIGeneratePage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Открыть сохранённый черновик' }));
    expect(routerPushMock).toHaveBeenCalledWith('/courses/course-1/edit');
    expect(screen.getByRole('button', { name: 'Создать новый курс' })).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it.each([
    { errors: ['generation_provider_interrupted'], course_id: 'course-1' },
    { errors: ['assessment_no_valid_questions'], course_id: null },
    { errors: undefined, course_id: 'course-1' },
  ])('preserves Continue for other interrupted jobs: %j', async (shape) => {
    const interruptedJob = { ...activeJob, ...shape, status: 'interrupted', stage: 'interrupted' };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: interruptedJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockResolvedValue({ data: { ...activeJob, status: 'pending', stage: 'queued' } } as any);

    render(<AIGeneratePage />);

    expect(await screen.findByRole('button', { name: 'Отменить' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Создать новый курс' })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: /^Продолжить/ }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/jobs/job-1/resume'));
    expect(routerPushMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Открыть сохранённый черновик' })).not.toBeInTheDocument();
  });

  it('keeps queued jobs cancellable from the queue action', async () => {
    const queuedJob = {
      ...activeJob, status: 'pending', stage: 'queued', progress: 0,
      queue_position: 2, estimated_wait_seconds: 30,
    };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: queuedJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<AIGeneratePage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Отменить задачу в очереди' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/jobs/job-1/cancel'));
    expect(screen.getByText(/Перетащите документы/)).toBeInTheDocument();
  });

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

  it('shows exact document indexing progress from the returned indexing job', async () => {
    localStorage.clear();
    const processingDocument = {
      ...readyDocuments[0],
      index: {
        ...readyDocuments[0].index,
        status: 'processing',
        chunks_total: null,
        chunks_indexed: null,
      },
    };
    const indexingJob = {
      id: 'index-job-1',
      status: 'running',
      progress_current: 3,
      progress_total: 8,
      estimated_remaining_seconds: 95,
    };
    let indexingJobPolls = 0;
    let catalogReads = 0;
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) {
        catalogReads += 1;
        return { data: { items: [processingDocument], page: { has_more: false } } } as any;
      }
      if (url === '/v1/ai/jobs?scope=mine') return { data: [] } as any;
      if (url === '/v1/ai/jobs/index-job-1') {
        indexingJobPolls += 1;
        return { data: indexingJobPolls === 1 ? indexingJob : { ...indexingJob, status: 'completed', estimated_remaining_seconds: 0 } } as any;
      }
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/documents/upload') {
        return { data: { id: processingDocument.id, indexing_job_id: indexingJob.id } } as any;
      }
      return { data: {} } as any;
    });

    const jobInterval = vi.spyOn(window, 'setInterval');
    const { container } = render(<AIGeneratePage />);
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: { files: [new File(['document'], 'rules.pdf', { type: 'application/pdf' })] },
    });

    expect(await screen.findByText('Индексация: 3 / 8')).toBeInTheDocument();
    expect(screen.getByText('38%')).toBeInTheDocument();
    expect(screen.getByText('Осталось примерно: 2 мин')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Индексация документа Правила ИБ' })).toHaveAttribute('aria-valuenow', '38');

    let intervalCallback: (() => void) | undefined;
    await waitFor(() => {
      intervalCallback = jobInterval.mock.calls.filter((call) => call[1] === 3000).at(-1)?.[0] as (() => void) | undefined;
      expect(intervalCallback).toBeDefined();
    });
    await act(async () => {
      intervalCallback!();
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(indexingJobPolls).toBe(2));
    await waitFor(() => expect(screen.queryByText('Индексация: 3 / 8')).not.toBeInTheDocument());
    expect(indexingJobPolls).toBe(2);
    expect(catalogReads).toBe(3);
    jobInterval.mockRestore();
  });

  it('uses a localized generic fallback instead of exposing backend upload details', async () => {
    localStorage.clear();
    apiMock.post.mockRejectedValueOnce({ response: { data: { detail: 'internal backend secret' } } });

    const { container } = render(<AIGeneratePage />);
    await screen.findByText(/Перетащите документы/);
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: { files: [new File(['content'], 'upload.pdf', { type: 'application/pdf' })] },
    });

    expect(await screen.findByText('Документ не загрузился. Проверьте формат файла и попробуйте ещё раз.')).toBeInTheDocument();
    expect(screen.queryByText('internal backend secret')).not.toBeInTheDocument();
  });

  it('does not let an old failed job take over a new generation form', async () => {
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
      if (url === '/v1/ai/jobs?scope=mine') return { data: [failedJob] } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);

    expect(await screen.findByText(/Перетащите документы/)).toBeInTheDocument();
    expect(screen.queryByText('SoftTimeLimitExceeded: generation failed')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Создать новый курс' })).not.toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalledWith('/v1/ai/generate-course', expect.anything());
  });

  it('maps an approval-required publish conflict before the raw API detail', async () => {
    const completedJob = { ...activeJob, status: 'completed', stage: 'completed', progress: 100 };
    let jobReads = 0;
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) {
        jobReads += 1;
        return { data: jobReads === 1 ? activeJob : completedJob } as any;
      }
      if (url === `/v1/courses/${activeJob.course_id}/preview`) return { data: { source_documents: [] } } as any;
      if (url === `/v1/courses/${activeJob.course_id}`) return { data: { id: activeJob.course_id, title: 'Курс', description: '', review_status: 'approved', status: 'draft' } } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === `/v1/courses/${activeJob.course_id}/publish`) {
        throw { response: { data: { detail: { code: 'approval_required' } } } };
      }
      return { data: {} } as any;
    });

    const jobInterval = vi.spyOn(window, 'setInterval');
    render(<AIGeneratePage />);
    expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
    let intervalCallback: (() => void) | undefined;
    await waitFor(() => {
      intervalCallback = jobInterval.mock.calls.find((call) => call[1] === 3000)?.[0] as (() => void) | undefined;
      expect(intervalCallback).toBeDefined();
    });
    await act(async () => {
      intervalCallback!();
      await Promise.resolve();
      await Promise.resolve();
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Опубликовать курс' }));

    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith(
      'Не удалось опубликовать курс',
      expect.objectContaining({ description: 'Для курса включено отдельное согласование. Откройте «Согласование» и получите решение рецензента. Если оно не требуется, отключите настройку там.' }),
    ));
    jobInterval.mockRestore();
  });

  it('opens a clean document step instead of restoring a completed review from an earlier visit', async () => {
    const completedJob = { ...activeJob, status: 'completed', stage: 'completed', progress: 100, errors: ['assessment_no_valid_questions'] };
    localStorage.setItem('ai_generation_workflow_context', JSON.stringify({
      job_id: completedJob.id,
      program_id: 'program-1',
    }));
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: [], page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${activeJob.id}`) return { data: completedJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<AIGeneratePage />);

    expect(await screen.findByText(/Перетащите документы/)).toBeInTheDocument();
    expect(screen.queryByText('Старый курс')).not.toBeInTheDocument();
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
    expect(localStorage.getItem('ai_generation_workflow_context')).toBeNull();
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
    expect(await screen.findByRole('textbox', { name: 'Целевая аудитория' })).toHaveAttribute('id', 'course-target-audience');
    expect(screen.getByRole('combobox', { name: 'Язык' })).toHaveAttribute('id', 'course-output-language');
    expect(await screen.findByRole('combobox', { name: 'Формат курса' })).toHaveValue('automatic');
    expect(screen.queryByRole('spinbutton', { name: 'Количество модулей' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Расширенные настройки структуры'));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Задать количество модулей вручную' }));
    expect(screen.getByRole('spinbutton', { name: 'Количество модулей' })).toBeInTheDocument();
  });

  it('shows an adaptive total lesson count and learning-duration range', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: {
        status: 'compatible', score: 1, analysis_mode: 'semantic', requires_decision: false, clusters: [],
        recommended_structure: {
          requested_format: 'automatic', resolved_format: 'brief', module_count: 1,
          lessons_per_module: 2, recommended_total_lessons: 2, hard_max_total_lessons: 2,
          duration_min_minutes: 6, duration_max_minutes: 10,
          estimated_duration_minutes: 8, quiz_count: 1, reason_codes: ['source_sparse'],
        },
      } } as any;
      return { data: {} } as any;
    });

    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));

    expect(await screen.findByText('Ориентир: 1 мод., около 2 содержательных уроков, 6–10 мин.')).toBeInTheDocument();
    expect(screen.getByText(/Оценка, а не обещанный результат/)).toBeInTheDocument();
    expect(screen.queryByText(/урока на модуль/)).not.toBeInTheDocument();
  });

  it('shows the automatic source interpretation and submits optional course intent', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: {
        status: 'unverified', score: null, analysis_mode: 'direct_source', requires_decision: false, clusters: [],
        source_passport: {
          confidence: 'high', teachable_units: 4,
          primary_sections: ['Коллекции'], supporting_sections: ['Номенклатура'],
          unknown_sections: [], warnings: ['supporting_sections_do_not_define_course_size'],
          sections: [],
        },
        recommended_structure: {
          requested_format: 'automatic', resolved_format: 'brief', module_count: 1,
          lessons_per_module: 4, recommended_total_lessons: 4, hard_max_total_lessons: 4,
          duration_min_minutes: 4, duration_max_minutes: 6,
          estimated_duration_minutes: 20, quiz_count: 1, reason_codes: ['source_capacity_passport'],
        },
      } } as any;
      if (url === '/v1/ai/generate-course') return { data: activeJob } as any;
      return { data: {} } as any;
    });

    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));

    expect(await screen.findByText(/Основные разделы: Коллекции/)).toBeInTheDocument();
    expect(screen.getByText(/Справочные разделы: Номенклатура/)).toBeInTheDocument();
    expect(screen.getByText(/Уверенность: высокая/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Что должен дать курс' }), {
      target: { value: 'Научить продавцов сравнивать коллекции под запрос клиента.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Генерировать курс/ }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/ai/generate-course',
      expect.objectContaining({
        course_intent: 'Научить продавцов сравнивать коллекции под запрос клиента.',
      }),
    ));
  });

  it('allows an unindexed source but requires original-file verification', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: {
        status: 'unverified', score: null, analysis_mode: 'direct_source', requires_decision: false, clusters: [],
      } } as any;
      return { data: {} } as any;
    });
    render(<AIGeneratePage />);

    const broken = await screen.findByRole('checkbox', { name: /Сломанный документ/ });
    expect(broken).toBeEnabled();
    fireEvent.click(broken);
    expect(await screen.findByText('Исходный файл прочитан. Можно создавать курс без поискового индекса.')).toBeInTheDocument();
    expect(screen.queryByText('Документы образуют одну тематическую группу. Можно проектировать единый курс.')).not.toBeInTheDocument();
    expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/document-compatibility', expect.objectContaining({ documents: ['doc-3'] }));
  });

  it('blocks generation if the original file cannot be verified', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockRejectedValue({ response: { status: 409, data: { detail: { code: 'direct_source_hash_mismatch' } } } });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Сломанный документ/ }));
    expect(await screen.findByText(/Не удалось проверить совместимость документов/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Генерировать курс \(/ })).toBeDisabled();
    expect(apiMock.post).not.toHaveBeenCalledWith('/v1/ai/generate-course', expect.anything());
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

describe('/ai/generate generation conflict recovery', () => {
  const existingJobId = '3ef30b99-7c2f-4f85-9a1e-2c3b4d5e6f70';
  const existingJob = {
    ...activeJob,
    id: existingJobId,
    course_id: null,
    status: 'running',
    progress: 42,
    stage: 'content_generation',
  } as any;

  function mockConflict(detail: Record<string, unknown>) {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') throw { response: { status: 409, data: { detail } } };
      return { data: {} } as any;
    });
  }

  it('keeps a 409 conflict actionable and reads the exact existing job without another generation POST', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return { data: existingJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);

    expect(await screen.findByText('Для этого набора документов уже идёт генерация.')).toBeInTheDocument();
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Открыть существующий прогресс' }));
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(`/v1/ai/jobs/${existingJobId}`));
    expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
  });

  it('synchronously fences two same-tick generate clicks before React rerenders', async () => {
    mockCatalogWith(readyDocuments);
    let resolveGeneration!: (value: unknown) => void;
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') return new Promise((resolve) => { resolveGeneration = resolve; });
      throw new Error(`Unexpected POST ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    await act(async () => {
      fireEvent.click(generateButton);
      fireEvent.click(generateButton);
    });
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
    resolveGeneration({ data: existingJob });
    await waitFor(() => expect(screen.getByText('Прогресс генерации')).toBeInTheDocument());
  });

  it('turns a valid 503 dispatch outcome into an exact read-only conflict', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return { data: existingJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') throw { response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: existingJobId } } } };
      throw new Error(`Unexpected POST ${url}`);
    });

    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);

    expect(await screen.findByText('Запрос принят, но подтверждение провайдера неизвестно.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Открыть существующий прогресс' })).toBeInTheDocument();
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Открыть существующий прогресс' }));
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(`/v1/ai/jobs/${existingJobId}`));
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
  });

  it('fails closed on a malformed 503 job id without enabling a retry or read', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') throw { response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: 'not-a-uuid' } } } };
      throw new Error(`Unexpected POST ${url}`);
    });

    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);

    expect(await screen.findByText('Ссылка на существующую генерацию недействительна.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Открыть существующий прогресс' })).not.toBeInTheDocument();
    expect(apiMock.get.mock.calls.some(([url]) => String(url).includes('/v1/ai/jobs/'))).toBe(false);
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
  });

  it('requires explicit acknowledgement before abandoning an unknown provider outcome and reconciles the exact job', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    let reads = 0;
    const abandonable = { ...existingJob, abandon_available: true };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) {
        reads += 1;
        return { data: reads > 1 ? { ...abandonable, status: 'abandoned' } : abandonable } as any;
      }
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockImplementation(async (url: string, body?: unknown) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') throw { response: { status: 409, data: { detail: { code: 'generation_already_in_progress', job_id: existingJobId } } } };
      if (url === `/v1/ai/jobs/${existingJobId}/abandon-unknown`) return { data: { ...abandonable, status: 'abandoned' } } as any;
      throw new Error(`Unexpected POST ${url} ${JSON.stringify(body)}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    fireEvent.click((await screen.findAllByRole('button', { name: /результат неизвестен/i }))[0]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Оставить прерванной/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /результат и стоимость неизвестны/i }));
    fireEvent.click(screen.getByRole('button', { name: /Оставить прерванной/ }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(`/v1/ai/jobs/${existingJobId}/abandon-unknown`, { acknowledge_outcome_and_cost_unknown: true }));
    await waitFor(() => expect(apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${existingJobId}`).length).toBeGreaterThan(1));
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
    expect(await screen.findByText(/оставлена прерванной/i)).toBeInTheDocument();
  });

  it('does not expose unknown-outcome abandonment when the server does not authorize it', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return { data: { ...existingJob, abandon_available: false } } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    expect(screen.queryByRole('button', { name: /результат неизвестен/i })).not.toBeInTheDocument();
  });

  it.each(['committed', 'read_failed', 'still_running', 'wrong_id'])('reconciles a lost abandonment acknowledgement (%s) without a second POST', async (outcome) => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    const abandonable = { ...existingJob, abandon_available: true };
    let reads = 0;
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) {
        reads += 1;
        if (reads > 1 && outcome === 'read_failed') throw new Error('read_unknown');
        if (reads > 1 && outcome === 'wrong_id') return { data: { ...abandonable, id: 'ffffffff-ffff-4fff-8fff-ffffffffffff', status: 'abandoned' } } as any;
        return { data: reads > 1 && outcome === 'committed' ? { ...abandonable, status: 'abandoned' } : abandonable } as any;
      }
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') throw { response: { status: 409, data: { detail: { code: 'generation_already_in_progress', job_id: existingJobId } } } };
      if (url === `/v1/ai/jobs/${existingJobId}/abandon-unknown`) throw new Error('acknowledgement_lost');
      throw new Error(`Unexpected POST ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    fireEvent.click((await screen.findAllByRole('button', { name: /результат неизвестен/i }))[0]);
    fireEvent.click(screen.getByRole('checkbox', { name: /результат и стоимость неизвестны/i }));
    fireEvent.click(screen.getByRole('button', { name: /Оставить прерванной/ }));
    await waitFor(() => expect(apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${existingJobId}`).length).toBeGreaterThan(1));
    expect(apiMock.post.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${existingJobId}/abandon-unknown`)).toHaveLength(1);
    if (outcome === 'committed') {
      expect(await screen.findByText(/оставлена прерванной/i)).toBeInTheDocument();
    } else {
      const refresh = await within(screen.getByRole('dialog')).findByRole('button', { name: 'Обновить статус' });
      fireEvent.click(refresh);
      await waitFor(() => expect(reads).toBeGreaterThan(2));
      expect(apiMock.post.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${existingJobId}/abandon-unknown`)).toHaveLength(1);
      expect(screen.queryByText(/оставлена прерванной/i)).not.toBeInTheDocument();
    }
  });

  it('rejects an invalid conflict id without attempting a read or a second POST', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: 'not-a-uuid' });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    expect(await screen.findByText('Ссылка на существующую генерацию недействительна.')).toBeInTheDocument();
    expect(apiMock.get.mock.calls.some(([url]) => String(url).includes('/v1/ai/jobs/'))).toBe(false);
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
  });

  it('keeps an exact-read failure visible and never retries generation automatically', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) throw { response: { status: 404 } };
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    expect(await screen.findByText('Не удалось прочитать существующую генерацию.')).toBeInTheDocument();
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
  });

  it('clears a terminal conflict only after the explicit read and does not auto-submit a new job', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return { data: { ...existingJob, status: 'completed', progress: 100 } } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    expect(await screen.findByText('Существующая генерация завершена. Можно явно подготовить новый курс.')).toBeInTheDocument();
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Вернуться к созданию курса' }));
    expect(screen.queryByText('Существующая генерация завершена. Можно явно подготовить новый курс.')).not.toBeInTheDocument();
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
  });

  it('drops a pending conflict when the selected source changes before it is read', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    expect(await screen.findByText('Для этого набора документов уже идёт генерация.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Охрана труда/ }));
    await waitFor(() => expect(screen.queryByText('Для этого набора документов уже идёт генерация.')).not.toBeInTheDocument());
    expect(apiMock.get).not.toHaveBeenCalledWith(`/v1/ai/jobs/${existingJobId}`);
  });

  it.each(['selection', 'selectionABA', 'session'])('ignores a delayed 409 after a %s scope change', async (change) => {
    mockCatalogWith(readyDocuments);
    let rejectGeneration!: (error: unknown) => void;
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') return new Promise((_, reject) => { rejectGeneration = reject; });
      return { data: {} } as any;
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    if (change === 'session') {
      act(() => useAuthStore.setState({ sessionEpoch: useAuthStore.getState().sessionEpoch + 1 }));
    } else {
      fireEvent.click(screen.getByRole('checkbox', { name: /Охрана труда/ }));
      if (change === 'selectionABA') fireEvent.click(screen.getByRole('checkbox', { name: /Охрана труда/ }));
    }
    await act(async () => {
      rejectGeneration({ response: { status: 409, data: { detail: { code: 'generation_already_in_progress', job_id: existingJobId } } } });
      await Promise.resolve();
    });
    expect(screen.queryByText('Для этого набора документов уже идёт генерация.')).not.toBeInTheDocument();
  });

  it('ignores a delayed GET after an A-B-A source selection cycle', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    let resolveRead!: (value: unknown) => void;
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return new Promise((resolve) => { resolveRead = resolve; });
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Охрана труда/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Охрана труда/ }));
    await act(async () => {
      resolveRead({ data: existingJob });
      await Promise.resolve();
    });
    expect(screen.queryByText('Прогресс генерации')).not.toBeInTheDocument();
  });

  it('keeps an admitted conflict across an access-token refresh for the same actor', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return { data: existingJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    useAuthStore.setState({ accessToken: 'rotated-token' });
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(`/v1/ai/jobs/${existingJobId}`));
    expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
  });

  it('restores an existing job with no inherited program context on a program-scoped page', async () => {
    window.history.pushState({}, '', '?program_id=requested-program');
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return { data: existingJob } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('ai_generation_workflow_context') || '{}').program_id).toBeNull();
    expect(apiMock.post.mock.calls.filter(([url]) => url === '/v1/ai/generate-course')).toHaveLength(1);
    window.history.pushState({}, '', '/');
  });

  it('clears the conflict banner when the recovered task is explicitly cancelled', async () => {
    mockCatalogWith(readyDocuments);
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return { data: { ...existingJob, progress: 76 } } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') throw { response: { status: 409, data: { detail: { code: 'generation_already_in_progress', job_id: existingJobId } } } };
      if (url === `/v1/ai/jobs/${existingJobId}/cancel`) return { data: { ...existingJob, status: 'cancelled', progress: 76 } } as any;
      throw new Error(`Unexpected POST ${url}`);
    });
    render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const generateButton = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    expect(await screen.findByText('Прогресс существующей генерации: 76%.')).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Отменить' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(`/v1/ai/jobs/${existingJobId}/cancel`));
    await waitFor(() => expect(screen.queryByText('Для этого набора документов уже идёт генерация.')).not.toBeInTheDocument());
  });

  it.each(['session', 'unmount', 'token'])('adopts a late successful admission only in its live actor scope (%s)', async (change) => {
    mockCatalogWith(readyDocuments);
    let resolveGeneration!: (value: unknown) => void;
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      if (url === '/v1/ai/generate-course') return new Promise((resolve) => { resolveGeneration = resolve; });
      throw new Error(`Unexpected POST ${url}`);
    });
    const view = render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const button = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    if (change === 'unmount') view.unmount();
    else act(() => useAuthStore.setState(change === 'session'
      ? { sessionEpoch: useAuthStore.getState().sessionEpoch + 1 }
      : { accessToken: 'same-actor-refreshed-token' }));
    await act(async () => { resolveGeneration({ data: existingJob }); await Promise.resolve(); });
    expect(localStorage.getItem('ai_active_job_id')).toBe(change === 'token' ? existingJobId : null);
    if (change === 'token') expect(await screen.findByText('Прогресс генерации')).toBeInTheDocument();
  });

  it('does not persist a conflict read after the page has unmounted', async () => {
    mockConflict({ code: 'generation_already_in_progress', job_id: existingJobId });
    let resolveRead!: (value: unknown) => void;
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/v1/documents/catalog')) return { data: { items: readyDocuments, page: { has_more: false } } } as any;
      if (url === `/v1/ai/jobs/${existingJobId}`) return new Promise((resolve) => { resolveRead = resolve; });
      throw new Error(`Unexpected GET ${url}`);
    });
    const view = render(<AIGeneratePage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила ИБ/ }));
    const button = await screen.findByRole('button', { name: /Генерировать/ });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть существующий прогресс' }));
    view.unmount();
    await act(async () => { resolveRead({ data: existingJob }); await Promise.resolve(); });
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
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

  it('does not report an expected reuse acknowledgement as a generation failure', async () => {
    mockCatalogWith(readyDocuments);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    apiMock.post.mockImplementation(async (url: string) => {
      if (url === '/v1/ai/document-compatibility') {
        return { data: { status: 'compatible', score: 1, requires_decision: false, clusters: [] } } as any;
      }
      if (url === '/v1/ai/generate-course') {
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
      throw new Error(`Unexpected POST ${url}`);
    });

    try {
      await selectTwoDocumentsAndClickGenerate();

      expect(await screen.findByRole('dialog', { name: 'Источник уже использован' })).toBeInTheDocument();
      expect(consoleError).not.toHaveBeenCalledWith('Generation failed', expect.anything());
    } finally {
      consoleError.mockRestore();
    }
  });

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
