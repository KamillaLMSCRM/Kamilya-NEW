import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { get: getMock, post: postMock } }));

import {
  applyLessonCorrection,
  createLessonCorrection,
  loadLessonCorrection,
  loadLessonCorrectionApplication,
} from '@/lib/lessonCorrection';

const lessonId = '11111111-1111-4111-8111-111111111111';
const planId = '22222222-2222-4222-8222-222222222222';
const courseId = '33333333-3333-4333-8333-333333333333';
const requestKey = '44444444-4444-4444-8444-444444444444';
const fingerprint = 'a'.repeat(64);
const afterFingerprint = 'b'.repeat(64);
const timestamp = '2026-10-05T10:00:00Z';
const provenance = { provider: 'openai', model_id: 'model-1', prompt_version: 'prompt-1', generator_version: 'generator-1' };
const proposal = { content: 'Исправленный текст урока', citations: [{ document_id: courseId, locator: 'page 4', evidence_hash: fingerprint }], provenance, quality_policy: 'human_review_required' };

function preview(state: 'pending' | 'ready' | 'failed', overrides: Record<string, unknown> = {}) {
  return {
    plan_id: planId,
    lesson_id: lessonId,
    revision: 3,
    state,
    expires_at: timestamp,
    fingerprint: state === 'ready' ? fingerprint : null,
    before_content: state === 'ready' ? 'Исходный текст урока' : null,
    proposal: state === 'ready' ? proposal : null,
    error_code: state === 'failed' ? 'provider_output_unparseable' : null,
    ...overrides,
  };
}

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    plan_id: planId,
    lesson_id: lessonId,
    course_id: courseId,
    revision: 3,
    fingerprint,
    before_sha256: fingerprint,
    after_sha256: afterFingerprint,
    applied_at: timestamp,
    state: 'applied',
    source_review: 'needs_review',
    quiz_review: 'needs_review',
    ...overrides,
  };
}

describe('lesson correction API client', () => {
  beforeEach(() => vi.clearAllMocks());

  it('posts the exact create request and preserves the abort signal', async () => {
    postMock.mockResolvedValue({ data: preview('pending') });
    const signal = new AbortController().signal;
    const request = { request_key: requestKey, lesson_id: lessonId, instruction: 'Уточни формулировку', locale: 'ru' as const };
    await expect(createLessonCorrection(request, signal)).resolves.toMatchObject({ state: 'pending', revision: 3 });
    expect(postMock).toHaveBeenCalledWith('/v1/methodologist-workbench/lesson-correction-previews', request, { signal });
  });

  it.each([
    ['pending', preview('pending')],
    ['ready', preview('ready')],
    ['failed', preview('failed')],
  ])('parses the %s state', async (_name, payload) => {
    postMock.mockResolvedValue({ data: payload });
    await expect(createLessonCorrection({ request_key: requestKey, lesson_id: lessonId, instruction: 'Исправь', locale: 'kk' })).resolves.toMatchObject(payload);
  });

  it.each([
    ['bad request key', { request_key: 'bad' }],
    ['blank instruction', { instruction: '   ' }],
    ['oversized instruction', { instruction: 'x'.repeat(4001) }],
    ['unsupported locale', { locale: 'de' }],
  ])('rejects %s locally without transport', async (_name, overrides) => {
    await expect(createLessonCorrection({ request_key: requestKey, lesson_id: lessonId, instruction: 'Исправь', locale: 'en', ...overrides } as never)).rejects.toThrow();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('rejects a create response for another lesson', async () => {
    postMock.mockResolvedValue({ data: preview('pending', { lesson_id: courseId }) });
    await expect(createLessonCorrection({ request_key: requestKey, lesson_id: lessonId, instruction: 'Исправь', locale: 'en' })).rejects.toThrow('lesson identity mismatch');
  });

  it('loads a preview and rejects a mismatched plan identity', async () => {
    getMock.mockResolvedValue({ data: preview('pending') });
    const signal = new AbortController().signal;
    await expect(loadLessonCorrection(planId, signal)).resolves.toMatchObject({ plan_id: planId });
    expect(getMock).toHaveBeenCalledWith(`/v1/methodologist-workbench/lesson-correction-previews/${planId}`, { signal });
    getMock.mockResolvedValue({ data: preview('pending', { plan_id: lessonId }) });
    await expect(loadLessonCorrection(planId)).rejects.toThrow('plan identity mismatch');
  });

  it.each([
    ['ready without fingerprint', preview('ready', { fingerprint: null })],
    ['ready without proposal', preview('ready', { proposal: null })],
    ['failed with proposal', preview('failed', { proposal })],
    ['invalid revision', preview('pending', { revision: 0 })],
    ['timezone-less expiry', preview('pending', { expires_at: '2026-10-05T10:00:00' })],
    ['citation locator too long', preview('ready', { proposal: { ...proposal, citations: [{ ...proposal.citations[0], locator: 'x'.repeat(121) }] } })],
  ])('rejects malformed response: %s', async (_name, payload) => {
    getMock.mockResolvedValue({ data: payload });
    await expect(loadLessonCorrection(planId)).rejects.toThrow();
  });

  it('rejects a non-string state that only stringifies to a valid state', async () => {
    getMock.mockResolvedValue({ data: preview('pending', { state: ['pending'] }) });
    await expect(loadLessonCorrection(planId)).rejects.toThrow();
  });

  it('posts the immutable apply seal and verifies the returned seal', async () => {
    postMock.mockResolvedValue({ data: receipt() });
    const signal = new AbortController().signal;
    await expect(applyLessonCorrection({ plan_id: planId, revision: 3, fingerprint }, signal)).resolves.toMatchObject({ state: 'applied' });
    expect(postMock).toHaveBeenCalledWith(`/v1/methodologist-workbench/lesson-correction-previews/${planId}/apply`, { plan_id: planId, revision: 3, fingerprint }, { signal });
    for (const mismatch of [{ plan_id: lessonId }, { revision: 4 }, { fingerprint: afterFingerprint }]) {
      postMock.mockResolvedValue({ data: receipt(mismatch) });
      await expect(applyLessonCorrection({ plan_id: planId, revision: 3, fingerprint })).rejects.toThrow(/mismatch/);
    }
  });

  it('does not retry or wrap transport and cancellation errors', async () => {
    const error = new Error('network');
    postMock.mockRejectedValue(error);
    await expect(applyLessonCorrection({ plan_id: planId, revision: 3, fingerprint })).rejects.toBe(error);
    expect(postMock).toHaveBeenCalledTimes(1);
    const cancellation = new Error('canceled');
    getMock.mockRejectedValue(cancellation);
    await expect(loadLessonCorrection(planId)).rejects.toBe(cancellation);
  });

  it('returns null only for a definite receipt 404', async () => {
    const notFound = { response: { status: 404 } };
    getMock.mockRejectedValue(notFound);
    await expect(loadLessonCorrectionApplication(planId)).resolves.toBeNull();
    const forbidden = { response: { status: 403 } };
    getMock.mockRejectedValue(forbidden);
    await expect(loadLessonCorrectionApplication(planId)).rejects.toBe(forbidden);
    getMock.mockResolvedValue({ data: receipt({ plan_id: lessonId }) });
    await expect(loadLessonCorrectionApplication(planId)).rejects.toThrow('plan identity mismatch');
  });
});
