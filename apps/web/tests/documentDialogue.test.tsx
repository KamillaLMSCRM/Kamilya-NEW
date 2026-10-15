import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DocumentDialogueDraft } from '@/lib/documentDialogue';

const apiMock = { get: vi.fn(), post: vi.fn(), patch: vi.fn() };
vi.mock('@/lib/api', () => ({ api: apiMock }));

const id = '00000000-0000-4000-8000-000000000001';
const requestId = '00000000-0000-4000-8000-000000000002';
const planId = '00000000-0000-4000-8000-000000000003';
const cursorId = '00000000-0000-4000-8000-000000000004';
const draft: DocumentDialogueDraft = {
  instruction: 'Create a short safety course',
  candidate: { target_audience: 'New staff', course_intent: 'Work safely', course_format: 'brief', language: 'en', source_strategy: 'single_topic', combination_goal: '' },
  language_confirmed: true,
  reuse_reason: null,
};
const task = {
  id, revision: 2, language: 'en',
  sources: [{ document_id: requestId, title: 'Safety guide', version: 3, content_sha256: 'a'.repeat(64), index_revision: 4 }],
  draft, plan_id: null, source_stale: false, pending_request_id: null, interrupted_request_id: null,
  exchanges: [], created_at: '2026-10-15T10:00:00Z', updated_at: '2026-10-15T10:01:00Z',
};
const previewPlan = { state: 'preview_ready', plan_id: planId, revision: 1, fingerprint: 'c'.repeat(64), expires_at: '2026-10-15T12:00:00Z', instruction: draft.instruction,
  generation: { documents: [requestId], ...draft.candidate, language_confirmed: true },
  sources: [{ document_id: requestId, title: 'Safety guide', version: 3, content_sha256: 'a'.repeat(64), index_revision: 4 }] };
const submittedPlan = { state: 'submitted', plan_id: planId, job: { id: 'job-1', status: 'running', job_type: 'course_generation', course_id: null, progress: 20, stage: 'generation', message: 'running' } };

vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: (state: any) => unknown) => selector({ user: { role: 'methodologist', user_id: 'actor-1' }, accessToken: 'token' }) }));
vi.mock('@/store/languageStore', () => ({ useLanguageStore: (selector: (state: any) => unknown) => selector({ lang: 'en' }) }));

describe('document dialogue transport', () => {
  afterEach(() => { vi.clearAllMocks(); window.history.replaceState({}, '', '/methodologist-workbench'); });

  it('creates a task with an idempotency locator and reopens the exact task by URL identity', async () => {
    apiMock.post.mockResolvedValue({ data: task });
    apiMock.get.mockResolvedValue({ data: task });
    const { createDocumentDialogue, getDocumentDialogue } = await import('@/lib/documentDialogue');
    const created = await createDocumentDialogue({ task_id: id, document_ids: [requestId], language: 'en', draft });
    expect(apiMock.post).toHaveBeenCalledWith('/v1/methodologist-workbench/document-dialogues', { task_id: id, document_ids: [requestId], language: 'en', draft }, undefined);
    expect(await getDocumentDialogue(created.id)).toEqual(created);
    expect(apiMock.get).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}`, undefined);
  });

  it('saves only on explicit PATCH, messages with a stable request key, and previews by saved revision', async () => {
    apiMock.patch.mockResolvedValue({ data: task });
    apiMock.post.mockResolvedValue({ data: task });
    const preview = { state: 'preview_ready', plan_id: requestId, revision: 1, fingerprint: 'b'.repeat(64), expires_at: '2026-10-15T12:00:00Z', instruction: draft.instruction,
      generation: { documents: [requestId], ...draft.candidate, language_confirmed: true },
      sources: [{ document_id: requestId, title: 'Safety guide', version: 3, content_sha256: 'a'.repeat(64), index_revision: 4 }] };
    apiMock.post.mockImplementation(async (url: string) => url.endsWith('/preview') ? { data: preview } : { data: task });
    const { messageDocumentDialogue, parseDocumentDialogueDraft, previewDocumentDialogue, saveDocumentDialogue } = await import('@/lib/documentDialogue');
    expect(parseDocumentDialogueDraft(draft, 'en')).toEqual(draft);
    await saveDocumentDialogue(id, 1, draft, 'en');
    expect(apiMock.patch).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}`, { expected_revision: 1, draft }, undefined);
    await messageDocumentDialogue(id, requestId, 2, '  Make the audience supervisors  ');
    expect(apiMock.post).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/messages`, { request_id: requestId, expected_revision: 2, instruction: 'Make the audience supervisors' }, undefined);
    expect((await previewDocumentDialogue(id, 2)).plan_id).toBe(requestId);
    expect(apiMock.post).toHaveBeenLastCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/preview`, { expected_revision: 2 }, undefined);
  });

  it('rejects invalid ownership locators, wrong task identities, and source language mixing', async () => {
    const { createDocumentDialogue, getDocumentDialogue, parseDocumentDialogueTask } = await import('@/lib/documentDialogue');
    await expect(getDocumentDialogue('bad-id')).rejects.toThrow();
    await expect(createDocumentDialogue({ task_id: id, document_ids: [requestId, requestId], language: 'en', draft })).rejects.toThrow();
    expect(() => parseDocumentDialogueTask({ ...task, draft: { ...draft, candidate: { ...draft.candidate, language: 'kk' } } })).toThrow();
    apiMock.get.mockResolvedValue({ data: { ...task, id: requestId } });
    await expect(getDocumentDialogue(id)).rejects.toThrow(/identity/);
  });

  it('validates content answers and retrieves only matching source citations and authenticated blobs', async () => {
    const citation = { number: 1, document_id: requestId, title: 'Safety guide', version: 3, content_sha256: 'a'.repeat(64), index_revision: 4, chunk_id: 'd'.repeat(64), quote: 'Wear protective equipment.' };
    const answered = { state: 'answered', status: 'supported', answer: 'Wear protective equipment.', citations: [citation] };
    const answerTask = { ...task, exchanges: [{ id: planId, instruction: 'What equipment?', state: 'completed', response: answered, error_code: null, created_at: task.updated_at }] };
    const { parseDocumentDialogueTask, messageDocumentContentDialogue, getDocumentContentSourceExcerpt, downloadDocumentContentSource } = await import('@/lib/documentDialogue');
    expect(parseDocumentDialogueTask(answerTask).exchanges[0].response).toEqual(answered);
    expect(() => parseDocumentDialogueTask({ ...answerTask, exchanges: [{ ...answerTask.exchanges[0], response: { ...answered, citations: [{ ...citation, version: 2 }] } }] })).toThrow(/does not match/);
    expect(() => parseDocumentDialogueTask({ ...answerTask, exchanges: [{ ...answerTask.exchanges[0], response: { ...answered, answer: 'x'.repeat(8001) } }] })).toThrow();
    apiMock.post.mockResolvedValue({ data: answerTask });
    await messageDocumentContentDialogue(task as any, requestId, ' What equipment? ');
    expect(apiMock.post).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/content-messages`, { request_id: requestId, expected_revision: 2, instruction: 'What equipment?' }, undefined);
    await expect(messageDocumentContentDialogue({ ...task, plan_id: planId } as any, requestId, 'question')).rejects.toThrow(/without a linked plan/);
    apiMock.get.mockResolvedValueOnce({ data: { citation, excerpt: 'Wear protective equipment before entry.' } });
    expect(await getDocumentContentSourceExcerpt(task as any, planId, citation)).toEqual({ citation, excerpt: 'Wear protective equipment before entry.' });
    expect(apiMock.get).toHaveBeenLastCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/sources/${planId}/1`, undefined);
    const blob = new Blob(['private source bytes'], { type: 'application/pdf' });
    apiMock.get.mockResolvedValueOnce({ data: blob, headers: { 'content-disposition': 'attachment; filename="..\\unsafe.pdf"' } });
    const downloaded = await downloadDocumentContentSource(task as any, planId, citation);
    expect(downloaded.blob).toBe(blob);
    expect(downloaded.filename).toBe('unsafe.pdf');
    expect(apiMock.get).toHaveBeenLastCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/sources/${planId}/1/download`, { responseType: 'blob' });
  });

  it('allows verified citations on not-found answers while enforcing citation validation for every status', async () => {
    const { parseDocumentDialogueTask } = await import('@/lib/documentDialogue');
    const citation = { number: 1, document_id: requestId, title: 'Safety guide', version: 3, content_sha256: 'a'.repeat(64), index_revision: 4, chunk_id: 'd'.repeat(64), quote: 'Wear protective equipment.' };
    const parseAnswer = (status: 'supported' | 'not_found' | 'conflict', citations: unknown[]) => parseDocumentDialogueTask({
      ...task,
      exchanges: [{ id: planId, instruction: 'What equipment?', state: 'completed', response: { state: 'answered', status, answer: 'No complete answer was found.', citations }, error_code: null, created_at: task.updated_at }],
    }).exchanges[0].response;

    expect(parseAnswer('not_found', [])).toMatchObject({ state: 'answered', status: 'not_found', citations: [] });
    expect(parseAnswer('not_found', [citation])).toMatchObject({ state: 'answered', status: 'not_found', citations: [citation] });
    expect(parseAnswer('supported', [citation])).toMatchObject({ state: 'answered', status: 'supported', citations: [citation] });
    expect(parseAnswer('conflict', [citation])).toMatchObject({ state: 'answered', status: 'conflict', citations: [citation] });
    expect(() => parseAnswer('supported', [])).toThrow(/citation set/);
    expect(() => parseAnswer('conflict', [])).toThrow(/citation set/);

    for (const status of ['supported', 'not_found', 'conflict'] as const) {
      expect(() => parseAnswer(status, [{ ...citation, quote: '' }])).toThrow(/Invalid document content citation/);
      expect(() => parseAnswer(status, [{ ...citation, document_id: id }])).toThrow(/does not match task sources/);
    }
  });

  it('defaults to content questions, keeps linked plans immutable, and renders citation text without HTML', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    const citation = { number: 1, document_id: requestId, title: 'Safety guide', version: 3, content_sha256: 'a'.repeat(64), index_revision: 4, chunk_id: 'd'.repeat(64), quote: '<script>quoted text</script>' };
    const answerTask = { ...task, exchanges: [{ id: planId, instruction: 'What is required?', state: 'completed', response: { state: 'answered', status: 'supported', answer: 'Use eye protection.', citations: [citation] }, error_code: null, created_at: task.updated_at }] };
    apiMock.get.mockImplementation(async (url: string) => url.includes('/sources/') ? { data: { citation, excerpt: 'Eye protection is required before entering the area.' } }
      : url.includes('/document-dialogues/') ? { data: answerTask } : { data: { tasks: [], has_more: false, next_before: null } });
    apiMock.post.mockResolvedValue({ data: answerTask });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    const questionBox = await screen.findByLabelText('Ask about the selected documents');
    expect(screen.getByRole('heading', { level: 3, name: 'Dialogue with documents' })).toBeInTheDocument();
    expect(screen.getByLabelText('Dialogue mode')).toHaveValue('question');
    expect(screen.getByText('<script>quoted text</script>')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open source citation' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(await screen.findByText('Eye protection is required before entering the area.')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/sources/${planId}/1`, expect.anything());
    const downloadButton = screen.getByRole('button', { name: 'Download original document' });
    expect(downloadButton).toHaveClass('h-auto', 'min-h-10', 'w-full', 'whitespace-normal', 'sm:w-auto');
    expect(downloadButton.parentElement).toHaveClass('flex', 'flex-col', 'sm:flex-row');
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    fireEvent.change(questionBox, { target: { value: 'What is required?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask question' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/content-messages`, expect.objectContaining({ instruction: 'What is required?' }), expect.anything()));
  });

  it('keeps archived citation text visible but blocks opening when the source is stale', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    const citation = { number: 1, document_id: requestId, title: 'Safety guide', version: 3, content_sha256: 'a'.repeat(64), index_revision: 4, chunk_id: 'd'.repeat(64), quote: 'Archived quote.' };
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/')
      ? { data: { ...task, source_stale: true, exchanges: [{ id: planId, instruction: 'Question', state: 'completed', response: { state: 'answered', status: 'supported', answer: 'Archived answer.', citations: [citation] }, error_code: null, created_at: task.updated_at }] } }
      : { data: { tasks: [], has_more: false, next_before: null } });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(await screen.findByText('Archived answer.')).toBeInTheDocument();
    expect(screen.getByText('Archived quote.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open source citation' })).toBeDisabled();
    expect(apiMock.get).not.toHaveBeenCalledWith(expect.stringContaining('/sources/'), expect.anything());
  });

  it('allows an explicit new-key message after reload projects an interrupted request', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    let reloadCount = 0;
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/')
      ? { data: reloadCount++ === 0 ? task : { ...task, interrupted_request_id: requestId } }
      : { data: { tasks: [], has_more: false, next_before: null } });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    await screen.findByLabelText('Ask about the selected documents');
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved task' }));
    expect(await screen.findByText(/previous request was interrupted/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Ask about the selected documents'), { target: { value: 'Try again explicitly' } });
    expect(screen.getByRole('button', { name: 'Ask question' })).toBeEnabled();
    apiMock.post.mockResolvedValue({ data: task });
    fireEvent.click(screen.getByRole('button', { name: 'Ask question' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/content-messages`, expect.objectContaining({ instruction: 'Try again explicitly' }), expect.anything()));
    expect(apiMock.post.mock.calls.at(-1)?.[1].request_id).not.toBe(requestId);
  });

  it('does not send a content question for an existing plan and explains that a new task is required', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/') ? { data: { ...task, plan_id: planId } }
      : url.includes('/document-plans/') ? { data: previewPlan }
        : { data: { tasks: [], has_more: false, next_before: null } });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(await screen.findByText(/This task already has a plan/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled();
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('requires a selected source to start a content dialogue but not course audience or goal', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues')
      ? { data: { tasks: [], has_more: false, next_before: null } }
      : { data: { items: [{ id: requestId, title: 'Safety guide', filename: 'guide.pdf', content_type: 'application/pdf', size: 10, description: '', category: 'general', index: { status: 'ready', revision: 4 }, version: 3, is_latest: true, lifecycle_status: 'active' }], page: { has_more: false } } });
    apiMock.post.mockImplementation(async (_url: string, body: any) => ({ data: { ...task, id: body.task_id, language: body.language, sources: task.sources, draft: body.draft } }));
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(await screen.findByText(/Course brief fields are not needed for questions/)).toBeInTheDocument();
    const start = screen.getByRole('button', { name: 'Start dialogue' });
    expect(start).toBeDisabled();
    expect(screen.getByLabelText('Audience')).toHaveValue('');
    expect(screen.getByLabelText('Course goal')).toHaveValue('');
    fireEvent.click(screen.getByRole('checkbox', { name: /Safety guide/ }));
    expect(start).toBeEnabled();
    fireEvent.click(start);
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/methodologist-workbench/document-dialogues', expect.objectContaining({ document_ids: [requestId], draft: expect.objectContaining({ candidate: expect.objectContaining({ target_audience: '', course_intent: '' }) }) }), expect.anything()));
    expect(apiMock.post).toHaveBeenCalledTimes(1);
  });

  it('requires explicit GET reconciliation after an ambiguous content-message outcome', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/') ? { data: task } : { data: { tasks: [], has_more: false, next_before: null } });
    apiMock.post.mockRejectedValue(new Error('connection lost'));
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.change(await screen.findByLabelText('Ask about the selected documents'), { target: { value: 'What equipment?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask question' }));
    expect(await screen.findByText(/The question outcome is not confirmed/)).toBeInTheDocument();
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved task' }));
    await waitFor(() => expect(screen.queryByText(/The question outcome is not confirmed/)).not.toBeInTheDocument());
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.get).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}`, expect.anything());
  });

  it('requires GET reconciliation after a definitive 4xx question failure before using the updated revision', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    const failedTask = { ...task, revision: 4, exchanges: [{ id: requestId, instruction: 'What equipment?', state: 'failed', response: null, error_code: 'invalid_response', created_at: task.updated_at }] };
    let detailReads = 0;
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/')
      ? { data: detailReads++ === 0 ? task : failedTask }
      : { data: { tasks: [], has_more: false, next_before: null } });
    apiMock.post.mockRejectedValueOnce({ response: { status: 422, data: { detail: 'invalid_response' } } }).mockResolvedValueOnce({ data: failedTask });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    const composer = await screen.findByLabelText('Ask about the selected documents');
    fireEvent.change(composer, { target: { value: 'What equipment?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask question' }));
    expect(await screen.findByText(/The question outcome is not confirmed/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask question' })).toBeDisabled();
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved task' }));
    await waitFor(() => expect(screen.queryByText(/The question outcome is not confirmed/)).not.toBeInTheDocument());
    expect(screen.getByText('failed')).toBeInTheDocument();
    fireEvent.change(composer, { target: { value: 'Try a new question' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask question' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(2));
    expect(apiMock.post.mock.calls[1][1].expected_revision).toBe(4);
    expect(apiMock.post.mock.calls[1][1].request_id).not.toBe(apiMock.post.mock.calls[0][1].request_id);
  });

  it('keeps task creation out of effects and requires an explicit save before preview', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const catalogItem = { id: requestId, title: 'Safety guide', filename: 'guide.pdf', content_type: 'application/pdf', size: 10, description: '', category: 'general', index: { status: 'ready', revision: 4 }, version: 3, is_latest: true, lifecycle_status: 'active' };
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues')
      ? { data: { tasks: [], has_more: false, next_before: null } }
      : { data: { items: [catalogItem], page: { has_more: false } } });
    apiMock.post.mockImplementation(async (url: string, body: any) => {
      if (url.endsWith('/document-dialogues')) return { data: { ...task, id: body.task_id, draft: body.draft } };
      if (url.endsWith('/preview')) return { data: { state: 'preview_ready', plan_id: requestId, revision: 1, fingerprint: 'b'.repeat(64), expires_at: '2026-10-15T12:00:00Z', instruction: 'Create a short safety course', generation: { documents: [requestId], ...draft.candidate, course_intent: 'Teach safe work', language_confirmed: true }, sources: task.sources } };
      throw new Error('Unexpected POST');
    });
    apiMock.patch.mockImplementation(async (url: string, body: any) => ({ data: { ...task, id: url.split('/').pop(), revision: body.expected_revision + 1, draft: body.draft } }));
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    await screen.findByText('Safety guide');
    expect(apiMock.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('checkbox', { name: /Safety guide/ }));
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'en' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start dialogue' }));
    await screen.findByText(/Task:/);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText('Course goal'), { target: { value: 'Teach safe work' } });
    expect(screen.getAllByRole('button', { name: 'Prepare plan' })[0]).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save parameters' }));
    await waitFor(() => expect(apiMock.patch).toHaveBeenCalled());
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Prepare plan' })[0]).toBeEnabled());
    fireEvent.click(screen.getAllByRole('button', { name: 'Prepare plan' })[0]);
    expect(await screen.findByText(/Plan ready/)).toBeInTheDocument();
  });

  it('reopens the linked submitted plan and restores its same job receipt', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/')
      ? { data: { ...task, plan_id: planId } }
      : url.includes('/document-plans/') ? { data: submittedPlan } : { data: { tasks: [], has_more: false, next_before: null } });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(await screen.findByText(/Task:.*running/)).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-plans/${planId}`, expect.anything());
    expect(screen.getAllByRole('button', { name: 'Prepare plan' })[0]).toBeDisabled();
  });

  it('uses the task-owned plan instead of restoring a stale legacy plan URL', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    const oldPlanId = '00000000-0000-4000-8000-000000000009';
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}&document_plan=${oldPlanId}`);
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/')
      ? { data: { ...task, plan_id: null } }
      : { data: { tasks: [], has_more: false, next_before: null } });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    await screen.findByText(/Task:/);
    expect(apiMock.get).not.toHaveBeenCalledWith(`/v1/methodologist-workbench/document-plans/${oldPlanId}`, expect.anything());
  });

  it('lets an explicitly prepared task replace a linked plan confirmed expired by GET', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/')
      ? { data: { ...task, plan_id: planId } }
      : url.includes('/document-plans/') ? Promise.reject({ response: { status: 409, data: { detail: 'expired' } } }) : { data: { tasks: [], has_more: false, next_before: null } });
    apiMock.post.mockImplementation(async (url: string) => url.endsWith('/preview') ? { data: previewPlan } : Promise.reject(new Error('unexpected POST')));
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    await screen.findByText(/Task:/);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Prepare plan' }))[0]);
    expect(await screen.findByText(/Plan ready/)).toBeInTheDocument();
    expect(apiMock.post).toHaveBeenCalledWith(`/v1/methodologist-workbench/document-dialogues/${id}/preview`, { expected_revision: task.revision }, expect.anything());
  });

  it('keeps an unknown linked plan opaque, blocks preview, and offers explicit new-task reset', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/document-dialogues/')) return { data: { ...task, plan_id: planId } };
      if (url.includes('/document-plans/')) throw { response: { status: 404 } };
      return { data: { tasks: [], has_more: false, next_before: null } };
    });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    expect(await screen.findByText(/The plan outcome is not confirmed/)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Prepare plan' })[0]).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Start new preparation' }));
    expect(new URLSearchParams(window.location.search).has('document_task')).toBe(false);
    expect(screen.getByRole('button', { name: 'Start dialogue' })).toBeInTheDocument();
  });

  it('treats a lost confirm response as ambiguous and reconciles with an explicit plan GET', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    let confirmAttempted = false;
    apiMock.get.mockImplementation(async (url: string) => url.includes('/document-dialogues/')
      ? { data: { ...task, plan_id: planId } }
      : url.includes('/document-plans/') ? { data: confirmAttempted ? submittedPlan : previewPlan } : { data: { tasks: [], has_more: false, next_before: null } });
    apiMock.post.mockImplementation(async (url: string) => {
      if (url.endsWith('/confirm')) { confirmAttempted = true; throw new Error('connection lost'); }
      throw new Error('unexpected POST');
    });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm and launch' }));
    expect(await screen.findByText(/Confirmation may have completed/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm and launch' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Recover plan' }));
    expect(await screen.findByText(/Task:.*running/)).toBeInTheDocument();
  });

  it('keeps a failed create locator for GET recovery and allows reset only after definitive 404', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/document-dialogues/')) throw { response: { status: 404 } };
      if (url.includes('/document-dialogues')) return { data: { tasks: [], has_more: false, next_before: null } };
      return { data: { items: [{ id: requestId, title: 'Safety guide', filename: 'guide.pdf', content_type: 'application/pdf', size: 10, description: '', category: 'general', index: { status: 'ready', revision: 4 }, version: 3, is_latest: true, lifecycle_status: 'active' }], page: { has_more: false } } };
    });
    apiMock.post.mockRejectedValue(new Error('connection lost'));
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /Safety guide/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Start dialogue' }));
    await screen.findByRole('alert');
    const provisionalId = new URLSearchParams(window.location.search).get('document_task');
    expect(provisionalId).toMatch(/^[0-9a-f-]{36}$/i);
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved task' }));
    expect(await screen.findByText(/The task was not found/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start new preparation' }));
    expect(new URLSearchParams(window.location.search).has('document_task')).toBe(false);
  });

  it('does not carry an unsent message into another saved preparation', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_task=${id}`);
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/document-dialogues/')) return { data: { ...task, id: url.split('/').pop() } };
      if (url.includes('/document-dialogues')) return { data: { tasks: [
        { id, title: 'First preparation', updated_at: task.updated_at, plan_id: null },
        { id: cursorId, title: 'Second preparation', updated_at: task.updated_at, plan_id: null },
      ], has_more: false, next_before: null } };
      return { data: { items: [], page: { has_more: false } } };
    });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    await screen.findByText(/Task:/);
    const composer = screen.getAllByRole('textbox').find((input) => input.getAttribute('maxLength') === '4000' && input !== screen.getByLabelText('Instruction'));
    expect(composer).toBeDefined();
    fireEvent.change(composer!, { target: { value: 'Unsent instruction for first preparation' } });
    fireEvent.change(screen.getByLabelText('Recent preparations'), { target: { value: cursorId } });
    await screen.findByText(new RegExp(`Task: ${cursorId}`));
    expect(composer).toHaveValue('');
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('clears a legacy ready plan when explicitly starting a saved preparation', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?document_plan=${planId}`);
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/document-plans/')) return { data: previewPlan };
      if (url.includes('/document-dialogues')) return { data: { tasks: [], has_more: false, next_before: null } };
      return { data: { items: [{ id: requestId, title: 'Safety guide', filename: 'guide.pdf', content_type: 'application/pdf', size: 10, index: { status: 'ready', revision: 4 }, version: 3, lifecycle_status: 'active' }], page: { has_more: false } } };
    });
    apiMock.post.mockImplementation(async (_url: string, body: any) => ({ data: { ...task, id: body.task_id, draft: body.draft } }));
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    await screen.findByText(/Plan ready/);
    fireEvent.click(screen.getByRole('button', { name: 'Start dialogue' }));
    await screen.findByText(/Task:/);
    expect(screen.queryByText(/Plan ready/)).not.toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).has('document_plan')).toBe(false);
  });

  it('ignores a late pagination response after opening a task', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    let resolvePage!: (value: unknown) => void;
    apiMock.get.mockImplementation((url: string) => {
      if (url.includes('?before=')) return new Promise((resolve) => { resolvePage = resolve; });
      if (url.includes('/document-dialogues/')) return Promise.resolve({ data: { ...task, id } });
      if (url.includes('/document-dialogues')) return Promise.resolve({ data: { tasks: [{ id, title: 'Safety guide', updated_at: task.updated_at, plan_id: null }], has_more: true, next_before: cursorId } });
      return Promise.resolve({ data: { items: [{ id: requestId, title: 'Safety guide', filename: 'guide.pdf', content_type: 'application/pdf', size: 10, description: '', category: 'general', index: { status: 'ready', revision: 4 }, version: 3, is_latest: true, lifecycle_status: 'active' }], page: { has_more: false } } });
    });
    const { default: DocumentWorkbench } = await import('@/features/methodologist-workbench/DocumentWorkbench');
    render(<DocumentWorkbench />);
    fireEvent.click(await screen.findByRole('button', { name: 'Show more' }));
    fireEvent.change(screen.getByLabelText('Recent preparations'), { target: { value: id } });
    await screen.findByText(/Task:/);
    resolvePage({ data: { tasks: [{ id: requestId, title: 'Late page', updated_at: task.updated_at, plan_id: null }], has_more: false, next_before: null } });
    await waitFor(() => expect(screen.queryByRole('option', { name: 'Late page' })).not.toBeInTheDocument());
  });
});
