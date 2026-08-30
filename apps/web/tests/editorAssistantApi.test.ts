import { beforeEach, describe, expect, it, vi } from 'vitest';

const postMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { post: postMock } }));

import { EDITOR_ASSISTANT_INTENTS, EditorAssistantPreviewApiError, requestQuestionAssistantPreview } from '@/lib/editorAssistant';

const request = { request_key: '11111111-1111-4111-8111-111111111111', preview_key: '22222222-2222-4222-8222-222222222222', intent: 'add_context' as const, instruction: 'Добавь контекст' };
const resourceIds = { quiz: '33333333-3333-3333-3333-333333333333', question: '44444444-4444-4444-4444-444444444444' };
const pending = { request_id: request.request_key, preview_id: request.preview_key, state: 'pending', applicability: 'not_applicable', base_snapshot_token: 'a'.repeat(64), operations: [], validation: null, source: { source_reference_count: 0, references: [] }, provenance: null, failure: null };
const completed = { ...pending, state: 'completed', applicability: 'applicable', operations: [{ operation: 'replace', field_path: 'question.answer_options', before_value: [{ choice_id: '11111111-1111-4111-8111-111111111112', text: 'Да', is_correct: true }, { choice_id: '11111111-1111-4111-8111-111111111113', text: 'Нет', is_correct: false }], after_value: [{ choice_id: '11111111-1111-4111-8111-111111111112', text: 'Да', is_correct: true }, { choice_id: '11111111-1111-4111-8111-111111111113', text: 'Не совсем', is_correct: false }] }], validation: { status: 'pass', issues: [] }, source: { source_reference_count: 1, references: [{ source_id: 'source-1', document_title: 'Регламент', locator: 'с. 4' }] }, provenance: { prompt_version: 'v1', generator_version: 'v1', validator_version: 'v1' } };

function utf8Bytes(value: unknown) { return new TextEncoder().encode(JSON.stringify(value)).length; }
function payloadAtProjectedBytes(target: number) {
  const answerIds = Array.from({ length: 20 }, (_, index) => `aaaaaaaa-aaaa-aaaa-aaaa-${String(index + 1).padStart(12, '0')}`);
  const beforeOptions = answerIds.map((choice_id, index) => ({ choice_id, text: index === 0 ? 'Правильный' : 'Неверный', is_correct: index === 0 }));
  const afterOptions = beforeOptions.map((option, index) => ({ ...option, text: index === 0 ? option.text : 'Изменённый вариант' }));
  const textOperation = { operation: 'replace' as const, field_path: 'question.text' as const, before_value: 'До', after_value: 'После' };
  const answerOptionsOperation = { operation: 'replace' as const, field_path: 'question.answer_options' as const, before_value: beforeOptions, after_value: afterOptions };
  const explanationOperation = { operation: 'replace' as const, field_path: 'question.explanation' as const, before_value: 'До', after_value: 'После' };
  const payload = {
    ...completed,
    operations: [textOperation, answerOptionsOperation, explanationOperation],
    source: { source_reference_count: 8, references: Array.from({ length: 8 }, (_, index) => ({ source_id: `source-${index}`, document_title: 'Документ', locator: 'раздел' })) },
  };
  const fields: Array<{ maximum: number; get: () => string; set: (value: string) => void }> = [
    { maximum: 4000, get: () => textOperation.before_value, set: (value) => { textOperation.before_value = value; } },
    { maximum: 4000, get: () => textOperation.after_value, set: (value) => { textOperation.after_value = value; } },
    { maximum: 6000, get: () => explanationOperation.before_value, set: (value) => { explanationOperation.before_value = value; } },
    { maximum: 6000, get: () => explanationOperation.after_value, set: (value) => { explanationOperation.after_value = value; } },
    ...beforeOptions.slice(1).map((option) => ({ maximum: 1000, get: () => option.text, set: (value: string) => { option.text = value; } })),
    ...afterOptions.slice(1).map((option) => ({ maximum: 1000, get: () => option.text, set: (value: string) => { option.text = value; } })),
    ...payload.source.references.flatMap((reference) => [{ maximum: 240, get: () => reference.document_title, set: (value: string) => { reference.document_title = value; } }, { maximum: 240, get: () => reference.locator, set: (value: string) => { reference.locator = value; } }]),
    ...payload.source.references.map((reference) => ({ maximum: 120, get: () => reference.source_id, set: (value: string) => { reference.source_id = value; } })),
    { maximum: 120, get: () => payload.provenance.prompt_version, set: (value) => { payload.provenance.prompt_version = value; } },
    { maximum: 120, get: () => payload.provenance.generator_version, set: (value) => { payload.provenance.generator_version = value; } },
    { maximum: 120, get: () => payload.provenance.validator_version, set: (value) => { payload.provenance.validator_version = value; } },
    { maximum: 160, get: () => payload.base_snapshot_token, set: (value) => { payload.base_snapshot_token = value; } },
  ];
  let remaining = target - utf8Bytes(payload);
  for (const field of fields) {
    const increase = Math.min(remaining, field.maximum - Array.from(field.get()).length);
    field.set(`${field.get()}${'x'.repeat(increase)}`);
    remaining -= increase;
  }
  if (remaining !== 0 || utf8Bytes(payload) !== target) throw new Error('Boundary payload is not constructible with valid DTO fields.');
  return payload;
}

describe('question assistant API client', () => {
  beforeEach(() => vi.clearAllMocks());
  it('exports exactly the backend intent values', () => {
    expect(EDITOR_ASSISTANT_INTENTS).toEqual(['rewrite_wording', 'add_context', 'regenerate_distractors', 'balance_answer_length', 'add_or_rewrite_explanation']);
  });
  it('posts only the accepted preview request contract and parses a bounded pending response', async () => {
    postMock.mockResolvedValue({ data: pending });
    const requestWithForbiddenRuntimeFields = { ...request, tenant_id: 'forbidden', actor_id: 'forbidden', role: 'admin', question: { text: 'draft' }, choices: [], source_text: 'forbidden' };
    await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, requestWithForbiddenRuntimeFields)).resolves.toEqual(pending);
    expect(postMock).toHaveBeenCalledWith(`/v1/quizzes/${resourceIds.quiz}/questions/${resourceIds.question}/assistant/preview`, request);
    expect(Object.keys(postMock.mock.calls[0][1]).sort()).toEqual(['instruction', 'intent', 'preview_key', 'request_key']);
  });
  it('accepts an instruction at the exact 4000-code-point request boundary', async () => {
    postMock.mockResolvedValue({ data: pending });
    await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, { ...request, instruction: '😀'.repeat(4000) })).resolves.toEqual(pending);
    expect(postMock).toHaveBeenCalledTimes(1);
  });
  it.each([
    ['invalid quiz id', 'invalid', resourceIds.question, request],
    ['invalid question id', resourceIds.quiz, 'invalid', request],
    ['invalid request key', resourceIds.quiz, resourceIds.question, { ...request, request_key: 'invalid' }],
    ['invalid preview key', resourceIds.quiz, resourceIds.question, { ...request, preview_key: 'invalid' }],
    ['unsupported intent', resourceIds.quiz, resourceIds.question, { ...request, intent: 'change_correct_answer' }],
    ['empty instruction', resourceIds.quiz, resourceIds.question, { ...request, instruction: '' }],
    ['instruction above 4000 code points', resourceIds.quiz, resourceIds.question, { ...request, instruction: '😀'.repeat(4001) }],
  ])('rejects %s locally without an HTTP call', async (_name, quizId, questionId, candidate) => {
    await expect(requestQuestionAssistantPreview(quizId, questionId, candidate as typeof request)).rejects.toMatchObject({ status: null });
    expect(postMock).not.toHaveBeenCalled();
  });
  it.each([[65_536, true], [65_537, false]])('enforces the exact projected UTF-8 response boundary at %i bytes', async (bytes, accepted) => {
    const payload = payloadAtProjectedBytes(bytes);
    expect(utf8Bytes(payload)).toBe(bytes);
    postMock.mockResolvedValue({ data: payload });
    if (accepted) await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).resolves.toBeDefined();
    else await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toMatchObject({ status: 200 });
  });
  it.each([
    ['accepts option text at 1000 characters', { ...completed, operations: [{ ...completed.operations[0], after_value: [{ ...completed.operations[0].after_value[0] }, { ...completed.operations[0].after_value[1], text: 'x'.repeat(1000) }] }] }, true],
    ['rejects option text above 1000 characters', { ...completed, operations: [{ ...completed.operations[0], after_value: [{ ...completed.operations[0].after_value[0] }, { ...completed.operations[0].after_value[1], text: 'x'.repeat(1001) }] }] }, false],
    ['accepts eight sources', { ...completed, source: { source_reference_count: 8, references: Array.from({ length: 8 }, (_, index) => ({ source_id: `source-${index}`, document_title: 'Документ', locator: 'с. 1' })) } }, true],
    ['rejects nine sources', { ...completed, source: { source_reference_count: 9, references: Array.from({ length: 9 }, (_, index) => ({ source_id: `source-${index}`, document_title: 'Документ', locator: 'с. 1' })) } }, false],
  ])('%s', async (_name, payload, accepted) => {
    postMock.mockResolvedValue({ data: payload });
    if (accepted) await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).resolves.toBeDefined();
    else await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toBeInstanceOf(EditorAssistantPreviewApiError);
  });
  it.each([
    ['accepts a non-v4 UUID permitted by the backend', { ...pending, request_id: '11111111-1111-0111-0111-111111111111' }, true],
    ['rejects null question text before value', { ...completed, operations: [{ ...completed.operations[0], field_path: 'question.text', before_value: null, after_value: 'Новый текст' }] }, false],
    ['rejects null question text after value', { ...completed, operations: [{ ...completed.operations[0], field_path: 'question.text', before_value: 'Старый текст', after_value: null }] }, false],
    ['rejects null answer options before value', { ...completed, operations: [{ ...completed.operations[0], before_value: null }] }, false],
    ['rejects null answer options after value', { ...completed, operations: [{ ...completed.operations[0], after_value: null }] }, false],
    ['accepts null explanation', { ...completed, operations: [{ operation: 'replace', field_path: 'question.explanation', before_value: null, after_value: 'Новое пояснение' }] }, true],
    ['accepts a 240-code-point non-BMP document title', { ...completed, source: { source_reference_count: 1, references: [{ source_id: 'source-1', document_title: '😀'.repeat(240), locator: 'с. 4' }] } }, true],
    ['rejects a 241-code-point non-BMP document title', { ...completed, source: { source_reference_count: 1, references: [{ source_id: 'source-1', document_title: '😀'.repeat(241), locator: 'с. 4' }] } }, false],
    ['rejects control characters in document metadata', { ...completed, source: { source_reference_count: 1, references: [{ source_id: 'source-1', document_title: 'Регламент\n', locator: 'с. 4' }] } }, false],
  ])('%s', async (_name, payload, accepted) => {
    postMock.mockResolvedValue({ data: payload });
    if (accepted) await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).resolves.toBeDefined();
    else await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toBeInstanceOf(EditorAssistantPreviewApiError);
  });
  it.each([
    ['pending response with operations', { ...pending, operations: completed.operations }],
    ['completed response with an unsupported path', { ...completed, operations: [{ ...completed.operations[0], field_path: 'question.correct_answer_id' }] }],
    ['completed response with multiple correct options', { ...completed, operations: [{ ...completed.operations[0], after_value: [{ choice_id: 'a', text: 'Да', is_correct: true }, { choice_id: 'b', text: 'Тоже да', is_correct: true }] }] }],
    ['completed response with an appended distractor', { ...completed, operations: [{ ...completed.operations[0], after_value: [...completed.operations[0].after_value, { choice_id: '11111111-1111-4111-8111-111111111114', text: 'Лишний вариант', is_correct: false }] }] }],
    ['response carrying apply data', { ...completed, apply: { persisted: true } }],
    ['failed response without failure', { ...pending, state: 'failed' }],
  ])('rejects malformed %s as a safe API error', async (_name, payload) => {
    postMock.mockResolvedValue({ data: payload });
    await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toMatchObject({ status: 200 });
  });
  it('rejects oversized malformed response fields and excessive root keys before transport succeeds', async () => {
    postMock.mockResolvedValueOnce({ data: { ...pending, base_snapshot_token: 'x'.repeat(100_000) } });
    await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toBeInstanceOf(EditorAssistantPreviewApiError);
    const excessiveRoot = Object.fromEntries(Array.from({ length: 1000 }, (_, index) => [`unexpected_${index}`, index]));
    postMock.mockResolvedValueOnce({ data: excessiveRoot });
    await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toBeInstanceOf(EditorAssistantPreviewApiError);
  });
  it.each([
    [401, 'Сессия истекла'], [403, 'У вас нет доступа'], [404, 'Вопрос или его исходные материалы'], [409, 'Вопрос изменился или запрос конфликтует'], [422, 'Помощник не может подготовить предложение'], [500, 'Не удалось подготовить предложение'],
  ])('maps HTTP %s to understandable copy without retrying', async (status, message) => {
    postMock.mockRejectedValue({ isAxiosError: true, response: { status, data: { detail: 'Bounded backend detail.' } } });
    await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toThrow(message);
    expect(postMock).toHaveBeenCalledTimes(1);
  });
  it('drops an unbounded backend detail', async () => {
    postMock.mockRejectedValue({ isAxiosError: true, response: { status: 500, data: { detail: 'x'.repeat(241) } } });
    await expect(requestQuestionAssistantPreview(resourceIds.quiz, resourceIds.question, request)).rejects.toEqual(expect.objectContaining<Partial<EditorAssistantPreviewApiError>>({ safeDetail: null }));
  });
});
