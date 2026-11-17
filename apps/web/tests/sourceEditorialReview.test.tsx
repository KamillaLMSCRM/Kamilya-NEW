import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SourceEditorialReview from '@/features/source-editorial-review/SourceEditorialReview';
import type { SourceReview } from '@/features/source-editorial-review/contract';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), role: 'methodologist', epoch: 1,
  tenant: 'test-tenant', approval: undefined as string | undefined }));
const id = '3021ee52-3387-46b2-a6c4-a7bd36136ffa';
const approval = 'b5b93138-cf8e-4e06-a87b-278e21efe8e2';
vi.mock('next/navigation', () => ({ useParams: () => ({ id, approvalId: mocks.approval }) }));
vi.mock('@/lib/api', () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: 'ru' }) }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (select: (state: { sessionEpoch: number; user: { role: string; user_id: string; tenant_id: string } }) => unknown) =>
    select({ sessionEpoch: mocks.epoch, user: { role: mocks.role, user_id: 'actor', tenant_id: mocks.tenant } }),
}));

const quote = 'До 45 МРП применяется порядок А.';
const updated = 'До 45 МРП включительно применяется порядок А.';
const reason = 'Владелец регламента подтвердил границу.';
function fixture(): SourceReview {
  return {
    document_id: id, document_version: 1, title: 'Тестовый источник', revision: 3, status: 'in_review',
    error: null, automatic: [], approval: null, journal: [], original_text: quote, working_text: quote,
    questions: [{ id: 'boundary', start: 0, end: quote.length, quote, reason: 'Что делать при 45 МРП?', resolution: null }],
  };
}

describe('source editorial review', () => {
  afterEach(() => vi.useRealTimers());
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.role = 'methodologist';
    mocks.epoch = 1;
    mocks.tenant = 'test-tenant';
    mocks.approval = undefined;
  });

  it('polls only lightweight status while active and fetches the full terminal result once', async () => {
    vi.useFakeTimers();
    let status = 'queued';
    const endpoint = '/v1/documents/' + id + '/editorial-review';
    mocks.get.mockImplementation(async (url: string) => ({ data: url === endpoint
      ? { ...fixture(), revision: status === 'in_review' ? 20 : 3, status }
      : { required: true, documents: { [id]: status } } }));
    render(<SourceEditorialReview />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(mocks.get.mock.calls.filter(([url]) => url === endpoint)).toHaveLength(1);
    expect(mocks.get.mock.calls.filter(([url]) => url === '/v1/documents/editorial-review/status?document_ids=' + id)).toHaveLength(2);
    status = 'running';
    await act(async () => { await vi.advanceTimersByTimeAsync(4500); });
    expect(screen.getByText('Версия документа 1 · Редакция 3')).toBeVisible();
    status = 'in_review';
    await act(async () => { await vi.advanceTimersByTimeAsync(13500); });
    expect(mocks.get.mock.calls.filter(([url]) => url === endpoint)).toHaveLength(2);
    expect(screen.getByText('Версия документа 1 · Редакция 20')).toBeVisible();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('never overlaps a slow status poll and ignores its response after unmount', async () => {
    vi.useFakeTimers();
    let settle!: (value: unknown) => void;
    mocks.get.mockResolvedValueOnce({ data: { ...fixture(), status: 'running' } })
      .mockImplementationOnce(() => new Promise(resolve => { settle = resolve; }));
    const view = render(<SourceEditorialReview />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(18000); });
    expect(mocks.get).toHaveBeenCalledTimes(2);
    const signal = mocks.get.mock.calls[1][1].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { settle({ data: { required: true, documents: { [id]: 'in_review' } } }); });
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('does not apply an old poll after a continuation command changes the revision', async () => {
    vi.useFakeTimers();
    let settle!: (value: unknown) => void;
    mocks.get.mockResolvedValueOnce({ data: { ...fixture(), status: 'queued', continuation_pending: true } })
      .mockImplementationOnce(() => new Promise(resolve => { settle = resolve; }));
    mocks.post.mockResolvedValue({ data: { ...fixture(), revision: 4, status: 'queued', continuation_pending: true } });
    render(<SourceEditorialReview />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(4500); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Продолжить проверку' })); });
    await act(async () => { settle({ data: { required: true, documents: { [id]: 'failed' } } }); });
    expect(screen.getByText('Версия документа 1 · Редакция 4')).toBeVisible();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it('keeps the saved review and offers reload on malformed lightweight status', async () => {
    vi.useFakeTimers();
    mocks.get.mockResolvedValueOnce({ data: { ...fixture(), status: 'running' } })
      .mockResolvedValue({ data: { required: true, documents: {} } });
    render(<SourceEditorialReview />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(4500); });
    expect(screen.getByRole('alert')).toBeVisible();
    expect(screen.getByText('Версия документа 1 · Редакция 3')).toBeVisible();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('discards an old tenant/session poll without loading its terminal snapshot', async () => {
    vi.useFakeTimers();
    let settle!: (value: unknown) => void;
    mocks.get.mockResolvedValueOnce({ data: { ...fixture(), status: 'running' } })
      .mockImplementationOnce(() => new Promise(resolve => { settle = resolve; }))
      .mockResolvedValueOnce({ data: { ...fixture(), revision: 30, title: 'Другой кабинет' } });
    const view = render(<SourceEditorialReview />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(4500); });
    mocks.tenant = 'another-owned-test-tenant';
    mocks.epoch = 2;
    view.rerender(<SourceEditorialReview />);
    await act(async () => {});
    await act(async () => { settle({ data: { required: true, documents: { [id]: 'in_review' } } }); });
    expect(screen.getByText('Другой кабинет')).toBeVisible();
    expect(screen.getByText('Версия документа 1 · Редакция 30')).toBeVisible();
    expect(mocks.get).toHaveBeenCalledTimes(3);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('does not poll a pinned historical approval', async () => {
    vi.useFakeTimers();
    mocks.approval = approval;
    mocks.get.mockResolvedValueOnce({ data: { ...fixture(), status: 'running' } });
    render(<SourceEditorialReview />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(18000); });
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.get.mock.calls[0][0]).toBe('/v1/documents/' + id + '/editorial-review/' + approval);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('shows the literal source entry so a short quotation still identifies the product', async () => {
    const data = fixture();
    data.questions[0].source_labels = ['00000017'];
    mocks.get.mockResolvedValue({ data });
    render(<SourceEditorialReview />);
    expect(await screen.findByText('Позиция в источнике: 00000017')).toBeVisible();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('only explicitly rechecks an older table review and preserves the revision guard', async () => {
    mocks.get.mockResolvedValue({ data: { ...fixture(), can_recheck: true } });
    mocks.post.mockResolvedValue({ data: { ...fixture(), revision: 4, status: 'queued', can_recheck: false } });
    render(<SourceEditorialReview />);
    expect(await screen.findByText(/Повторная проверка пересоздаст список замечаний/)).toBeVisible();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить проверку' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post).toHaveBeenCalledWith('/v1/documents/' + id + '/editorial-review',
      expect.objectContaining({ action: 'start', expected_revision: 3 }));
    expect(screen.queryByRole('button', { name: 'Повторить проверку' })).not.toBeInTheDocument();
  });

  it('requires explicit acknowledgement of unknown outcome and cost before retry', async () => {
    const data = { ...fixture(), status: 'failed' as const, error: 'source_review_timeout',
      requires_retry_acknowledgement: true };
    mocks.get.mockResolvedValue({ data });
    mocks.post.mockResolvedValue({ data: { ...data, status: 'queued', revision: 4, error: null,
      requires_retry_acknowledgement: false } });
    render(<SourceEditorialReview />);
    const ack = await screen.findByRole('checkbox', { name: /Результат предыдущего запроса и его стоимость неизвестны/ });
    const retry = screen.getByRole('button', { name: 'Повторить проверку' });
    expect(retry).toBeDisabled();
    fireEvent.click(ack);
    fireEvent.click(retry);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/v1/documents/' + id + '/editorial-review',
      expect.objectContaining({ action: 'start', expected_revision: 3, acknowledge_outcome_and_cost_unknown: true })));
  });

  it('keeps an unknown visual call held instead of offering a misleading retry', async () => {
    mocks.get.mockResolvedValue({ data: { ...fixture(), status: 'failed', error: 'source_review_provider_outcome_unknown',
      requires_retry_acknowledgement: true, retry_blocked_unknown_visual: true } });
    render(<SourceEditorialReview />);
    expect(await screen.findByText(/Результат распознавания изображения неизвестен/)).toBeVisible();
    expect(screen.queryByRole('checkbox', { name: /Результат предыдущего запроса/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('holds an interrupted worker with an unknown outcome', async () => {
    mocks.get.mockResolvedValue({ data: { ...fixture(), status: 'interrupted',
      error: 'source_review_interrupted_outcome_unknown' } });
    render(<SourceEditorialReview />);
    expect(await screen.findByText(/Результат прерванной проверки и её стоимость неизвестны/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('requires fresh acknowledgement if a conflict reveals a different failed revision', async () => {
    const first = { ...fixture(), status: 'failed' as const, error: 'source_review_timeout',
      requires_retry_acknowledgement: true };
    mocks.get.mockResolvedValueOnce({ data: first }).mockResolvedValueOnce({ data: { ...first, revision: 4 } });
    mocks.post.mockRejectedValueOnce({ response: { status: 409 } });
    render(<SourceEditorialReview />);
    const ack = await screen.findByRole('checkbox', { name: /Результат предыдущего запроса и его стоимость неизвестны/ });
    fireEvent.click(ack);
    fireEvent.click(screen.getByRole('button', { name: 'Повторить проверку' }));
    await screen.findByText(/Редакция 4/);
    expect(ack).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled();
  });

  it('replays the same continuation request after an unconfirmed dispatch', async () => {
    const data = { ...fixture(), status: 'queued', continuation_pending: true };
    mocks.get.mockResolvedValue({ data });
    mocks.post.mockRejectedValueOnce({ response: { status: 503 } }).mockResolvedValueOnce({ data });
    render(<SourceEditorialReview />);
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить проверку' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Проверить сохранение' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[0][1]).toEqual(mocks.post.mock.calls[1][1]);
    expect(mocks.post.mock.calls[0][1]).toEqual(expect.objectContaining({ action: 'start', expected_revision: 3 }));
  });

  it('preserves a part selection on conflict and sends the server manifest identity', async () => {
    const current = { ...fixture(), questions: [], preparation: {
      policy: 'v1', sha256: 'a'.repeat(64), selected_part_ids: ['part-' + '1'.repeat(24)],
      parts: [
        { id: 'part-' + '1'.repeat(24), title: 'First', role: 'learning' as const, reason: 'Relevant', block_count: 1 },
        { id: 'part-' + '2'.repeat(24), title: 'Second', role: 'supporting' as const, reason: 'Additional', block_count: 1 },
      ], assets: [],
    } };
    mocks.get.mockResolvedValueOnce({ data: current }).mockResolvedValueOnce({ data: { ...current, revision: 4 } });
    mocks.post.mockRejectedValueOnce({ response: { status: 409 } });
    render(<SourceEditorialReview />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Second/ }));
    expect(screen.getByRole('button', { name: 'Утвердить редакцию' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Применить выбор' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('checkbox', { name: /Second/ })).toBeChecked();
    expect(mocks.post).toHaveBeenCalledWith('/v1/documents/' + id + '/editorial-review', expect.objectContaining({
      action: 'select_parts', expected_revision: 3, preparation_sha256: 'a'.repeat(64),
      selected_part_ids: ['part-' + '1'.repeat(24), 'part-' + '2'.repeat(24)],
    }));
  });

  it('requires a decision before approval and links to the exact approved version', async () => {
    const current = fixture();
    mocks.get.mockResolvedValue({ data: current });
    const resolved: SourceReview = { ...current, revision: 4, working_text: updated, questions: current.questions.map(question => ({
      ...question, resolution: { id: question.id, start: 0, end: quote.length, before: quote, after: updated, reason, decision: 'replace' },
    })) };
    mocks.post.mockResolvedValueOnce({ data: resolved }).mockResolvedValueOnce({ data: {
      ...resolved, revision: 5, status: 'approved', approval: {
        document_id: id, approval_id: approval, revision: 5, working_sha256: 'a'.repeat(64), created_at: '2026-11-06T00:00:00Z',
      },
    } });
    render(<SourceEditorialReview />);
    await screen.findByText('Что делать при 45 МРП?');
    expect(screen.getByRole('button', { name: 'Утвердить редакцию' })).toBeDisabled();
    expect(screen.queryByRole('link', { name: 'Перейти к генерации' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Согласованная формулировка'), { target: { value: updated } });
    fireEvent.change(screen.getByLabelText('Основание решения'), { target: { value: reason } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить решение' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Утвердить редакцию' })).toBeEnabled());
    expect(mocks.post).toHaveBeenCalledWith('/v1/documents/' + id + '/editorial-review',
      expect.objectContaining({ action: 'resolve', expected_revision: 3, replacement: updated, reason }));
    fireEvent.click(screen.getByRole('button', { name: 'Утвердить редакцию' }));
    expect(await screen.findByRole('link', { name: 'Перейти к генерации' })).toHaveAttribute('href', '/ai/generate?document_id=' + id);
    expect(screen.getByRole('link', { name: 'Открыть утверждённую редакцию' })).toHaveAttribute('href', '/documents/' + id + '/editorial-review/' + approval);
  });

  it('preserves typed wording across a revision conflict and reads the newer state', async () => {
    const data = fixture();
    mocks.get.mockResolvedValueOnce({ data }).mockResolvedValueOnce({ data: { ...data, revision: 4 } });
    mocks.post.mockRejectedValueOnce({ response: { status: 409 } });
    render(<SourceEditorialReview />);
    fireEvent.change(await screen.findByLabelText('Согласованная формулировка'), { target: { value: updated } });
    fireEvent.change(screen.getByLabelText('Основание решения'), { target: { value: reason } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить решение' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ваш несохранённый ввод');
    expect(await screen.findByText(/Редакция 4/)).toBeInTheDocument();
    expect(screen.getByLabelText('Согласованная формулировка')).toHaveValue(updated);
  });

  it('keeps an unconfirmed finding visible and requires an original quote for replacement', async () => {
    const review = fixture();
    review.questions[0] = { ...review.questions[0], start: null, end: null, quote: '',
      needs_source_verification: true };
    mocks.get.mockResolvedValue({ data: review });
    render(<SourceEditorialReview />);
    expect(await screen.findByText('Замечание не удалось подтвердить автоматически. Сверьте его с оригиналом.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Утвердить редакцию' })).toBeDisabled();
    expect(screen.getByLabelText('Точная цитата из оригинала')).toBeRequired();
    expect(screen.queryByRole('link', { name: 'Перейти к генерации' })).not.toBeInTheDocument();
  });

  it('lets the methodologist correct a missed issue and preserves the input when the quote cannot be located', async () => {
    const current = { ...fixture(), questions: [] };
    mocks.get.mockResolvedValue({ data: current });
    mocks.post.mockRejectedValueOnce({ response: { status: 409, data: { details: { code: 'source_review_quote_not_unique' } } } });
    render(<SourceEditorialReview />);
    fireEvent.click(await screen.findByRole('button', { name: 'Добавить правку' }));
    fireEvent.change(screen.getByLabelText('Точная цитата из оригинала'), { target: { value: quote } });
    fireEvent.change(screen.getByLabelText('Согласованная формулировка'), { target: { value: updated } });
    fireEvent.change(screen.getByLabelText('Основание решения'), { target: { value: reason } });
    expect(screen.getByRole('button', { name: 'Утвердить редакцию' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить правку' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Скопируйте точный фрагмент');
    expect(screen.getByLabelText('Согласованная формулировка')).toHaveValue(updated);
    expect(mocks.post).toHaveBeenCalledWith('/v1/documents/' + id + '/editorial-review',
      expect.objectContaining({ action: 'add_edit', expected_revision: 3, quote, replacement: updated, reason }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отменить ввод' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Отменить ввод' }));
    expect(screen.getByRole('button', { name: 'Утвердить редакцию' })).toBeEnabled();
  });

  it('explains a provider outage and submits only the selected PDF range', async () => {
    const failed: SourceReview = { ...fixture(), pdf: true, status: 'failed', original_text: null,
      working_text: null, questions: [], error: 'source_review_provider_unavailable' };
    mocks.get.mockResolvedValue({ data: failed });
    mocks.post.mockResolvedValue({ data: { ...failed, revision: 4, status: 'queued', error: null,
      pages: { first_page: 3, last_page: 9 } } });
    render(<SourceEditorialReview />);
    expect(await screen.findByText('Сервис проверки документа недоступен. Повторите проверку позже.')).toBeInTheDocument();
    const retry = screen.getByRole('button', { name: 'Повторить проверку' });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'С' }), { target: { value: '3' } });
    expect(retry).toBeDisabled();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'По' }), { target: { value: '9' } });
    fireEvent.click(retry);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/v1/documents/' + id + '/editorial-review',
      expect.objectContaining({ action: 'start', expected_revision: 3, pages: { first_page: 3, last_page: 9 } })));
    expect(await screen.findByText('Выбранные страницы: 3–9')).toBeInTheDocument();
  });

  it('starts a whole-document check for an uploaded Word file', async () => {
    const document: SourceReview = { ...fixture(), title: 'Регламент.docx', pdf: false,
      status: 'not_started', original_text: null, working_text: null, questions: [] };
    mocks.get.mockResolvedValue({ data: document });
    mocks.post.mockResolvedValue({ data: { ...document, revision: 4, status: 'queued' } });
    render(<SourceEditorialReview />);
    const start = await screen.findByRole('button', { name: 'Проверить документ' });
    expect(screen.queryByRole('group', { name: 'Страницы для проверки' })).not.toBeInTheDocument();
    fireEvent.click(start);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ action: 'start', expected_revision: 3 });
    expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('pages');
  });

  it.each(['failed', 'in_review'] as const)('explains stale preparation recovery in %s and prevents applying its old part selection', async status => {
    const failed: SourceReview = { ...fixture(), status, questions: [], error: 'source_review_preparation_stale',
      preparation: { policy: 'v1', sha256: 'a'.repeat(64), selected_part_ids: ['part-' + '1'.repeat(24)],
        parts: [{ id: 'part-' + '1'.repeat(24), title: 'Старая часть', role: 'learning', reason: 'Обучение', block_count: 1 }], assets: [] } };
    mocks.get.mockResolvedValue({ data: failed });
    mocks.post.mockResolvedValue({ data: { ...failed, revision: 4, status: 'queued', error: null } });
    render(<SourceEditorialReview />);
    expect(await screen.findByText(/Выбранные части требуют повторной проверки/)).toBeVisible();
    expect(screen.getByRole('checkbox', { name: /Старая часть/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Применить выбор' })).not.toBeInTheDocument();
    if (status === 'in_review') expect(screen.getByRole('button', { name: 'Утвердить редакцию' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить проверку' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/v1/documents/' + id + '/editorial-review',
      expect.objectContaining({ action: 'start', expected_revision: 3 })));
    expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('selected_part_ids');
  });

  it('does not fetch document text for an inactive role', () => {
    mocks.role = 'student';
    render(<SourceEditorialReview />);
    expect(mocks.get).not.toHaveBeenCalled();
  });
});
