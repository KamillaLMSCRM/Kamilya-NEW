import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiMock = { get: vi.fn(), post: vi.fn() };
let currentLang: 'ru' | 'kk' | 'en' = 'ru';
vi.mock('@/lib/api', () => ({ api: apiMock }));

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { user: { role: string; user_id: string } | null; accessToken: string }) => unknown) => selector({
    user: { role: 'methodologist', user_id: 'actor-1' },
    accessToken: 'token',
  }),
}));

vi.mock('@/store/languageStore', () => ({
  useLanguageStore: (selector: (state: { lang: 'ru' | 'kk' | 'en' }) => unknown) => selector({ lang: currentLang }),
}));

describe('DocumentWorkbench', () => {
  afterEach(() => { currentLang = 'ru'; });
  it('localizes the document controls and format labels for Kazakh and English while preserving wire values', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    apiMock.get.mockResolvedValue({ data: { items: [], page: { has_more: false } } });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    currentLang = 'kk';
    const first = render(<DocumentWorkbench />);
    expect(screen.getByRole('heading', { name: 'Құжат → курс жобасы' })).toBeInTheDocument();
    expect(screen.getByLabelText('Құжат жүктеу')).toBeInTheDocument();
    expect(screen.getByLabelText('Пішім')).toHaveValue('automatic');
    expect(screen.getByRole('option', { name: 'Қысқа' })).toHaveValue('brief');
    first.unmount();
    currentLang = 'en';
    render(<DocumentWorkbench />);
    expect(screen.getByRole('heading', { name: 'Document → course draft' })).toBeInTheDocument();
    expect(screen.getByLabelText('Upload document')).toBeInTheDocument();
    expect(screen.getByLabelText('Format')).toHaveValue('automatic');
    expect(screen.getByRole('option', { name: 'Detailed' })).toHaveValue('detailed');
    currentLang = 'ru';
  });

  it('keeps an active upload alive when the shell locale changes', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const document = { id: '00000000-0000-4000-8000-000000000001', title: 'Rules', filename: 'rules.pdf', content_type: 'application/pdf', size: 1, description: '', category: 'general', index: { status: 'ready', revision: 1 }, version: 1, is_latest: true, lifecycle_status: 'active' };
    apiMock.get.mockResolvedValue({ data: { items: [document], page: { has_more: false } } });
    let resolveUpload!: (value: unknown) => void;
    apiMock.post.mockReturnValue(new Promise((resolve) => { resolveUpload = resolve; }));
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    currentLang = 'ru';
    const view = render(<DocumentWorkbench />);
    const file = new File(['pdf'], 'rules.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('Загрузить документ'), { target: { files: [file] } });
    await waitFor(() => expect(apiMock.post).toHaveBeenCalled());
    currentLang = 'en';
    view.rerender(<DocumentWorkbench />);
    expect(apiMock.post.mock.calls[0][2].signal.aborted).toBe(false);
    expect(screen.getByRole('status')).toHaveTextContent('Загрузка документа');
    resolveUpload({ data: { id: document.id, indexing_job_id: null } });
    await waitFor(() => expect(screen.getByText('Rules')).toBeInTheDocument());
    currentLang = 'ru';
  });

  it('starts as a feature-gated document draft surface', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(screen.getByRole('heading', { name: /документ/i })).toBeInTheDocument();
  });

  it('does not render when the independent flag is disabled', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'false');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(screen.queryByRole('heading', { name: /документ/i })).not.toBeInTheDocument();
  });

  it('rejects malformed preview identities and preserves strict source bounds', async () => {
    const { isAIGenerateRequest, parseDocumentPlan } = await import('@/lib/documentWorkbench');
    const generation = {
      documents: ['00000000-0000-4000-8000-000000000001'], target_audience: '', course_intent: 'Научить сотрудников безопасной работе',
      course_format: 'automatic', language: 'ru', source_strategy: 'single_topic', combination_goal: '', language_confirmed: false,
    } as const;
    expect(isAIGenerateRequest(generation)).toBe(true);
    expect(isAIGenerateRequest({ ...generation, documents: [...generation.documents, ...generation.documents, ...generation.documents, ...generation.documents, ...generation.documents, ...generation.documents] })).toBe(false);
    expect(() => parseDocumentPlan({ state: 'preview_ready', plan_id: 'not-a-uuid' })).toThrow();
  });

  it('does not let a stale preview response replace edited input', async () => {
    apiMock.get.mockResolvedValue({ data: { items: [{ id: '00000000-0000-4000-8000-000000000001', title: 'Правила', filename: 'rules.pdf', content_type: 'application/pdf', size: 1, description: '', category: 'general', index: { status: 'ready', revision: 1 }, version: 1, is_latest: true, lifecycle_status: 'active' }], page: { has_more: false } } });
    let resolvePreview!: (value: unknown) => void;
    apiMock.post.mockReturnValue(new Promise((resolve) => { resolvePreview = resolve; }));
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила/ }));
    fireEvent.change(screen.getByLabelText('Инструкция'), { target: { value: 'Сделайте курс' } });
    fireEvent.change(screen.getByLabelText('Цель курса'), { target: { value: 'Научить сотрудников безопасной работе' } });
    fireEvent.click(screen.getByRole('button', { name: 'Подготовить план' }));
    fireEvent.change(screen.getByLabelText('Инструкция'), { target: { value: 'Новая инструкция' } });
    resolvePreview({});
    await waitFor(() => expect(screen.queryByText(/План готов/)).not.toBeInTheDocument());
  });

  it('restores a submitted plan and shows the server job without synthesizing one', async () => {
    const planId = '00000000-0000-4000-8000-000000000002';
    window.history.replaceState({}, '', `/methodologist-workbench?document_plan=${planId}`);
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-plans/')
      ? { data: { state: 'submitted', plan_id: planId, job: { id: 'job-1', status: 'running', job_type: 'course_generation', course_id: null, progress: 12, stage: 'ingestion', message: 'queued' } } }
      : { data: { items: [], page: { has_more: false } } });
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(await screen.findByText(/Задача: running/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Открыть курс' })).not.toBeInTheDocument();
    window.history.replaceState({}, '', '/methodologist-workbench');
  });

  it('uses the newly selected sources when replacing a restored preview', async () => {
    const planId = '00000000-0000-4000-8000-000000000002';
    const oldId = '00000000-0000-4000-8000-000000000001';
    const newId = '00000000-0000-4000-8000-000000000003';
    window.history.replaceState({}, '', `/methodologist-workbench?document_plan=${planId}`);
    const generation = { documents: [oldId], target_audience: 'Сотрудники', course_intent: 'Безопасная работа', course_format: 'standard', language: 'ru', source_strategy: 'single_topic', combination_goal: '', language_confirmed: false };
    const restored = { state: 'preview_ready', plan_id: planId, revision: 1, fingerprint: 'a'.repeat(64), expires_at: '2026-10-04T12:00:00Z', instruction: 'Сделайте курс', generation, sources: [{ document_id: oldId, title: 'Старый источник', version: 1, content_sha256: 'b'.repeat(64), index_revision: 1 }] };
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-plans/')
      ? { data: restored }
      : { data: { items: [
        { id: oldId, title: 'Старый источник', version: 1, lifecycle_status: 'active', index: { status: 'ready' } },
        { id: newId, title: 'Новый источник', version: 1, lifecycle_status: 'active', index: { status: 'ready' } },
      ], page: { has_more: false } } });
    apiMock.post.mockResolvedValue({ data: restored });
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(await screen.findByText(/План готов/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('checkbox', { name: /Старый источник/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Новый источник/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Подготовить план' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/methodologist-workbench/document-preview',
      expect.objectContaining({ generation: expect.objectContaining({ documents: [newId] }) }),
      expect.anything(),
    ));
    window.history.replaceState({}, '', '/methodologist-workbench');
  });

  it('reports a failed confirm without claiming submission', async () => {
    window.history.replaceState({}, '', '/methodologist-workbench');
    apiMock.get.mockResolvedValue({ data: { items: [{ id: '00000000-0000-4000-8000-000000000001', title: 'Правила', filename: 'rules.pdf', content_type: 'application/pdf', size: 1, description: '', category: 'general', index: { status: 'ready', revision: 1 }, version: 1, is_latest: true, lifecycle_status: 'active' }], page: { has_more: false } } });
    apiMock.post.mockImplementation(async (url: string) => {
      if (url.endsWith('/document-preview')) return { data: { state: 'preview_ready', plan_id: '00000000-0000-4000-8000-000000000002', revision: 1, fingerprint: 'a'.repeat(64), expires_at: '2026-10-04T12:00:00Z', instruction: 'Сделайте курс', generation: { documents: ['00000000-0000-4000-8000-000000000001'], target_audience: '', course_intent: 'Научить сотрудников безопасной работе', course_format: 'automatic', language: 'ru', source_strategy: 'single_topic', combination_goal: '', language_confirmed: false }, sources: [{ document_id: '00000000-0000-4000-8000-000000000001', title: 'Правила', version: 1, content_sha256: 'b'.repeat(64), index_revision: 1 }] } };
      throw { response: { status: 409 } };
    });
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила/ }));
    fireEvent.change(screen.getByLabelText('Инструкция'), { target: { value: 'Сделайте курс' } });
    fireEvent.change(screen.getByLabelText('Цель курса'), { target: { value: 'Научить сотрудников безопасной работе' } });
    fireEvent.click(screen.getByRole('button', { name: 'Подготовить план' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить и запустить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/устарел|подтвердить план/i);
    expect(screen.queryByText(/Задача:/)).not.toBeInTheDocument();
  });

  it('invalidates the old preview and language acknowledgement after interpretation', async () => {
    window.history.replaceState({}, '', '/methodologist-workbench');
    const catalogItem = { id: '00000000-0000-4000-8000-000000000001', title: 'Правила', filename: 'rules.pdf', content_type: 'application/pdf', size: 1, description: '', category: 'general', index: { status: 'ready', revision: 1 }, version: 1, is_latest: true, lifecycle_status: 'active' };
    apiMock.get.mockResolvedValue({ data: { items: [catalogItem], page: { has_more: false } } });
    apiMock.post.mockImplementation(async (url: string) => url.endsWith('/document-preview')
      ? { data: { state: 'preview_ready', plan_id: '00000000-0000-4000-8000-000000000002', revision: 1, fingerprint: 'a'.repeat(64), expires_at: '2026-10-04T12:00:00Z', instruction: 'Сделайте курс', generation: { documents: [catalogItem.id], target_audience: '', course_intent: 'Цель курса', course_format: 'automatic', language: 'ru', source_strategy: 'single_topic', combination_goal: '', language_confirmed: true }, sources: [{ document_id: catalogItem.id, title: 'Правила', version: 1, content_sha256: 'b'.repeat(64), index_revision: 1 }] } }
      : { data: { state: 'interpreted', candidate: { target_audience: 'Новые сотрудники', course_intent: 'Цель на казахском', course_format: 'standard', language: 'kk', source_strategy: 'single_topic', combination_goal: '' } } });
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Правила/ }));
    fireEvent.change(screen.getByLabelText('Инструкция'), { target: { value: 'Сделайте курс' } });
    fireEvent.change(screen.getByLabelText('Цель курса'), { target: { value: 'Цель курса' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /подтверждаю язык/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Подготовить план' }));
    expect(await screen.findByText(/План готов/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Интерпретировать' }));
    await waitFor(() => expect(screen.queryByText(/План готов/)).not.toBeInTheDocument());
    expect(screen.getByRole('checkbox', { name: /подтверждаю язык/i })).not.toBeChecked();
    expect(screen.getByLabelText('Язык')).toHaveValue('kk');
  });

  it('preserves the factual upload indexing failure instead of a timeout', async () => {
    window.history.replaceState({}, '', '/methodologist-workbench');
    apiMock.get.mockImplementation(async (url: string) => url.includes('/ai/jobs/')
      ? { data: { id: 'index-job', status: 'failed', message: 'Файл не удалось прочитать' } }
      : { data: { items: [], page: { has_more: false } } });
    apiMock.post.mockResolvedValue({ data: { id: 'source-id', indexing_job_id: 'index-job' } });
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.change(screen.getByLabelText('Загрузить документ'), { target: { files: [new File(['content'], 'failed.pdf')] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Файл не удалось прочитать');
    expect(screen.queryByText(/не завершилась в допустимое время/)).not.toBeInTheDocument();
  });

  it('shows upload indexing and reloads the catalog after processing becomes ready', async () => {
    window.history.replaceState({}, '', '/methodologist-workbench');
    const ready = { id: '00000000-0000-4000-8000-000000000003', title: 'Новый документ', filename: 'new.pdf', content_type: 'application/pdf', size: 1, description: '', category: 'general', index: { status: 'ready', revision: 1 }, version: 1, is_latest: true, lifecycle_status: 'active' };
    let catalogCalls = 0;
    apiMock.get.mockImplementation(async (url: string) => url.includes('/ai/jobs/')
      ? { data: { id: 'index-job', status: catalogCalls > 1 ? 'completed' : 'running', job_type: 'document_indexing', course_id: null, progress: 100, stage: 'indexing', message: '' } }
      : { data: { items: catalogCalls++ > 0 ? [ready] : [], page: { has_more: false } } });
    apiMock.post.mockResolvedValue({ data: { id: ready.id, indexing_job_id: 'index-job' } });
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    const file = new File(['content'], 'new.pdf', { type: 'application/pdf' });
    const originalSetTimeout = window.setTimeout;
    const timeout = vi.spyOn(window, 'setTimeout').mockImplementation(((handler: TimerHandler) => originalSetTimeout(handler, 0)) as typeof window.setTimeout);
    fireEvent.change(screen.getByLabelText('Загрузить документ'), { target: { files: [file] } });
    expect(await screen.findByText(/Индексация документа/)).toBeInTheDocument();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(await screen.findByText('Новый документ')).toBeInTheDocument();
    timeout.mockRestore();
  });

  it('keeps an upload and ready catalog item alive when instruction changes during indexing', async () => {
    window.history.replaceState({}, '', '/methodologist-workbench');
    const ready = { id: '00000000-0000-4000-8000-000000000004', title: 'Документ после изменения', filename: 'ready.pdf', content_type: 'application/pdf', size: 1, description: '', category: 'general', index: { status: 'ready', revision: 1 }, version: 1, is_latest: true, lifecycle_status: 'active' };
    let resolveUpload!: (value: unknown) => void;
    let catalogCalls = 0;
    apiMock.get.mockImplementation(async (url: string) => url.includes('/ai/jobs/')
      ? { data: { id: 'index-job', status: 'completed', job_type: 'document_indexing', course_id: null, progress: 100, stage: 'indexing', message: '' } }
      : { data: { items: catalogCalls++ > 0 ? [ready] : [], page: { has_more: false } } });
    apiMock.post.mockReturnValue(new Promise((resolve) => { resolveUpload = resolve; }));
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.change(screen.getByLabelText('Загрузить документ'), { target: { files: [new File(['content'], 'ready.pdf')] } });
    fireEvent.change(screen.getByLabelText('Инструкция'), { target: { value: 'Новая команда' } });
    resolveUpload({ data: { id: ready.id, indexing_job_id: 'index-job' } });
    expect(await screen.findByText('Документ после изменения')).toBeInTheDocument();
  });
});
