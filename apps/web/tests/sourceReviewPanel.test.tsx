import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SourceReviewPanel } from '@/features/course-authoring/SourceReviewPanel';

const auth = vi.hoisted(() => ({ value: { accessToken: 'synthetic-token', sessionEpoch: 1,
  user: { user_id: 'methodologist', tenant_id: 'tenant-1', role: 'methodologist' } } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: Object.assign(
  (selector: (value: typeof auth.value) => unknown) => selector(auth.value), { getState: () => auth.value }) }));

const fetchMock = vi.fn();
const done = vi.fn();
function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status }); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r; }); return { promise, resolve }; }
function details(courseId = 'course-1') {
  return { course_id: courseId, has_active_hold: true, content_snapshot_hash: 'a'.repeat(64),
    available_revisions: ['rev-1', 'rev-2'],
    source_documents: [
      { document_id: 'doc-1', title: 'Стандарт', filename: 'standard.docx', authoritative_revision: 'rev-1' },
      { document_id: 'doc-2', title: 'Правила', filename: 'rules.pdf', authoritative_revision: 'rev-2' },
    ], active_defects: [{ defect_id: 'p30-finding', description: 'Проверьте условие допуска.',
      target_title: 'Допуск: кто выполняет проверку?', evidence: { unverified: true,
        observation: 'Не указан статус исполнителя.', missing_condition: 'Полномочие не установлено.',
        possible_answers: ['Работник', 'Ответственный'], source_quotes: ['Проверку выполняет ответственное лицо.'] } },
      { defect_id: 'p30-editorial', description: 'Проверьте содержание и ключи.' }], resolutions_history: [],
    draft_review: { version: 'p30-editorial-draft-v1', generation_status: 'draft_prepared',
      self_review_status: 'needs_attention', human_review_required: true, issues: [],
      observations: [{ id: 'note', kind: 'source_observation', target_id: '', message: 'Информационная заметка.', source_refs: [], blocking: false }] },
  };
}
const props = { courseId: 'course-1', disabled: false, lang: 'ru', onResolved: done };
async function open() { fireEvent.click(screen.getByRole('button', { name: 'Открыть замечания и источники' })); await screen.findByText('Проверьте условие допуска.'); }
function complete() {
  screen.getAllByRole('textbox').forEach((field, i) => fireEvent.change(field, { target: { value: `Проверено по первоисточнику, решение ${i}.` } }));
  fireEvent.click(screen.getByRole('checkbox'));
}

describe('SourceReviewPanel', () => {
  beforeEach(() => {
    auth.value = { accessToken: 'synthetic-token', sessionEpoch: auth.value.sessionEpoch + 1,
      user: { user_id: 'methodologist', tenant_id: 'tenant-1', role: 'methodologist' } };
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://synthetic.invalid/api');
    vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); done.mockClear();
    fetchMock.mockImplementation(async (_url, init) => init?.method === 'POST' ? response({ id: 'course-1' }) : response(details()));
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it('keeps the draft usable and requires explicit per-issue decisions before submission', async () => {
    render(<SourceReviewPanel {...props} />);
    expect(fetchMock).not.toHaveBeenCalled();
    await open();
    expect(screen.getByText('Черновик подготовлен')).toBeInTheDocument();
    expect(screen.getByText('Информационная заметка.')).toBeInTheDocument();
    expect(screen.getByText('Допуск: кто выполняет проверку?')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Основание замечания — требует проверки'));
    expect(screen.getByText('Не указан статус исполнителя.')).toBeVisible();
    expect(screen.getByText('Проверку выполняет ответственное лицо.')).toBeVisible();
    const save = screen.getByRole('button', { name: 'Сохранить решения по этой версии' });
    expect(save).toBeDisabled();
    complete(); fireEvent.click(save);
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toContain('/course-1/resolve-source-uncertainty');
    expect(JSON.parse(posts[0][1].body)).toMatchObject({ expected_content_hash: 'a'.repeat(64),
      verified_revisions: { 'doc-1': 'rev-1', 'doc-2': 'rev-2' },
      defect_resolutions: [{ defect_id: 'p30-finding', action: 'manual_verification_passed' }, { defect_id: 'p30-editorial', action: 'manual_verification_passed' }] });
    expect(fetchMock.mock.calls.some(([url]) => /\/(review|publish)$/.test(String(url)))).toBe(false);
  });

  it('does not double-submit or automatically retry an unknown mutation outcome', async () => {
    const pending = deferred<Response>();
    fetchMock.mockImplementation(async (_url, init) => init?.method === 'POST' ? pending.promise : response(details()));
    render(<SourceReviewPanel {...props} />); await open(); complete();
    const save = screen.getByRole('button', { name: 'Сохранить решения по этой версии' });
    fireEvent.click(save); fireEvent.click(save);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    await act(async () => { pending.resolve(new Response('unparseable')); });
    expect(await screen.findByText(/Результат сохранения не подтверждён/)).toBeInTheDocument();
    expect(done).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });

  it('requires fresh inspection and fresh decisions after a concurrent edit conflict', async () => {
    fetchMock.mockImplementation(async (_url, init) => init?.method === 'POST' ? response({}, 409) : response(details()));
    render(<SourceReviewPanel {...props} />); await open(); complete();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить решения по этой версии' }));
    expect(await screen.findByText(/Содержание или источник изменились/)).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    await open();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getAllByRole('textbox').every((field) => (field as HTMLTextAreaElement).value === '')).toBe(true);
  });

  it('ignores an old course response and never exposes its findings in another course', async () => {
    const pending = deferred<Response>(); fetchMock.mockReturnValueOnce(pending.promise);
    const { rerender } = render(<SourceReviewPanel {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Открыть замечания и источники' }));
    rerender(<SourceReviewPanel {...props} courseId="course-2" />);
    await act(async () => { pending.resolve(response(details())); });
    expect(screen.queryByText('Проверьте условие допуска.')).not.toBeInTheDocument();
    expect(done).not.toHaveBeenCalled();
  });

  it('does not apply an old session mutation result to the new actor', async () => {
    const pending = deferred<Response>();
    fetchMock.mockImplementation(async (_url, init) => init?.method === 'POST' ? pending.promise : response(details()));
    const { rerender } = render(<SourceReviewPanel {...props} />); await open(); complete();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить решения по этой версии' }));
    auth.value = { ...auth.value, sessionEpoch: auth.value.sessionEpoch + 1,
      user: { ...auth.value.user, user_id: 'other-methodologist' } };
    rerender(<SourceReviewPanel {...props} />);
    await act(async () => { pending.resolve(response({ id: 'course-1' })); });
    expect(done).not.toHaveBeenCalled();
    expect(screen.queryByText(/Решения сохранены/)).not.toBeInTheDocument();
  });

  it('blocks unsaved content, unauthorized roles and unbound source revisions', async () => {
    const { rerender } = render(<SourceReviewPanel {...props} disabled />);
    expect(screen.getByRole('button')).toBeDisabled(); expect(fetchMock).not.toHaveBeenCalled();
    rerender(<SourceReviewPanel {...props} />);
    fetchMock.mockResolvedValueOnce(response({ ...details(), source_documents: [] }));
    await open(); complete();
    expect(screen.getByRole('button', { name: 'Сохранить решения по этой версии' })).toBeDisabled();
    auth.value = { ...auth.value, user: { ...auth.value.user, role: 'student' } };
    rerender(<SourceReviewPanel {...props} />);
    expect(screen.queryByRole('region', { name: 'Проверка черновика' })).not.toBeInTheDocument();
  });
});
