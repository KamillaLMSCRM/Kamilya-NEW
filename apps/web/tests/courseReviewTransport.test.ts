import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  clearStoredAuth: vi.fn(),
  getAccessToken: vi.fn(() => 'learner-token'),
  forceRefreshAndStoreSession: vi.fn(),
  getAuthSessionEpoch: vi.fn(() => 1),
  getCurrentUser: vi.fn(() => ({ user_id: 'reviewer-1', tenant_id: 'tenant-1', role: 'methodologist' })),
}));
vi.mock('@/lib/auth', () => authMocks);

import { api } from '@/lib/api';
import { getScopedReviewRequest, listApprovalRequests, saveReviewProgress, startReviewAttempt, submitReviewDecision, submitReviewTest, verifyReviewPin } from '@/lib/courseApproval';

describe('scoped review transport', () => {
  const originalAdapter = api.defaults.adapter;
  const calls: Array<{ url?: string; authorization?: string }> = [];

  beforeEach(() => {
    calls.length = 0;
    sessionStorage.clear();
    authMocks.getAccessToken.mockReturnValue('learner-token');
    authMocks.getAuthSessionEpoch.mockReset().mockReturnValue(1);
    authMocks.getCurrentUser.mockReset().mockReturnValue({ user_id: 'reviewer-1', tenant_id: 'tenant-1', role: 'methodologist' });
    authMocks.forceRefreshAndStoreSession.mockReset().mockResolvedValue(false);
    api.defaults.adapter = async (config) => {
      const headers = config.headers as { Authorization?: string; get?: (name: string) => string | undefined } | undefined;
      calls.push({ url: config.url, authorization: headers?.get?.('Authorization') ?? headers?.Authorization });
      if (config.url?.includes('/verify-pin')) {
        return { data: { review_token: 'scoped-review-token', work_item_id: 'work-item-1', request_id: 'request-1' }, status: 200, statusText: 'OK', headers: {}, config: config as InternalAxiosRequestConfig };
      }
      if (config.url?.includes('/course-review-requests/')) {
        return { data: { request_id: 'request-1', revision_id: 'revision-1', outcome: 'pending', delivery_mode: 'personal_link', due_at: null, reviewer: { reviewer_id: 'reviewer-1', reviewer_name: 'Reviewer', reviewer_email: 'reviewer@example.test', decision: 'pending', decision_at: null, required: true, delivery_state: 'accepted', access_state: 'active', activity_state: 'not_started', deadline_state: 'unset', outcome: 'pending', progress: {} }, all_required_approved: false }, status: 200, statusText: 'OK', headers: {}, config: config as InternalAxiosRequestConfig };
      }
      if (config.url?.includes('/course-approval-requests/') && config.url.includes('/attempts')) {
        return { data: { attempt_id: 'attempt-1', revision_id: 'revision-1', snapshot_sha256: 'sha256', activity_state: 'in_progress', lesson_position: 2, next_sequence: 9, snapshot: { schema_version: 1, release_version: 1, course: { id: 'course-1', title: 'Course' }, modules: [] } }, status: 200, statusText: 'OK', headers: {}, config: config as InternalAxiosRequestConfig };
      }
      return { data: [], status: 200, statusText: 'OK', headers: {}, config: config as InternalAxiosRequestConfig };
    };
  });

  afterEach(() => {
    api.defaults.adapter = originalAdapter;
  });

  it('carries the verified capability through scoped list/detail and attempt calls only', async () => {
    const verified = await verifyReviewPin('opaque-link-token', '123456');
    sessionStorage.setItem('course_review_token', verified.review_token);
    await getScopedReviewRequest(verified.review_token, verified.request_id);
    await startReviewAttempt(verified.request_id!, verified.review_token);
    await listApprovalRequests();

    expect(calls).toHaveLength(4);
    expect(calls[0]).toMatchObject({ url: expect.stringContaining('/course-review-access/'), authorization: undefined });
    expect(calls[1]).toMatchObject({ url: '/v1/course-review-requests/request-1', authorization: 'Bearer scoped-review-token' });
    expect(calls[2]).toMatchObject({ url: '/v1/course-approval-requests/request-1/attempts', authorization: 'Bearer scoped-review-token' });
    expect(calls[3]).toMatchObject({ url: '/v1/course-approval-requests', authorization: 'Bearer learner-token' });
    expect(authMocks.forceRefreshAndStoreSession).not.toHaveBeenCalled();
  });

  it('accepts valid resume metadata while safely defaulting invalid or missing values', async () => {
    const valid = await startReviewAttempt('request-1', 'scoped-review-token');
    expect(valid.lesson_position).toBe(2);
    expect(valid.next_sequence).toBe(9);
    api.defaults.adapter = async (config) => ({ data: { attempt_id: 'attempt-2', revision_id: 'revision-1', snapshot_sha256: 'sha256-2', activity_state: 'not_started', lesson_position: -1, next_sequence: 0, snapshot: { schema_version: 1, release_version: 1, course: { id: 'course-1', title: 'Course' }, modules: [] } }, status: 200, statusText: 'OK', headers: {}, config: config as InternalAxiosRequestConfig });
    const legacy = await startReviewAttempt('request-1', 'scoped-review-token');
    expect(legacy.lesson_position).toBeNull();
    expect(legacy.next_sequence).toBe(1);
    api.defaults.adapter = async (config) => ({ data: { attempt_id: 'attempt-3', revision_id: 'revision-1', snapshot_sha256: 'sha256-3', activity_state: 'not_started', snapshot: { schema_version: 1, release_version: 1, course: { id: 'course-1', title: 'Course' }, modules: [] } }, status: 200, statusText: 'OK', headers: {}, config: config as InternalAxiosRequestConfig });
    const missing = await startReviewAttempt('request-1', 'scoped-review-token');
    expect(missing.lesson_position).toBeNull();
    expect(missing.next_sequence).toBe(1);
  });

  it('encodes the optional approval course filter while preserving the legacy token slot', async () => {
    await listApprovalRequests(undefined, 'course/with spaces');
    expect(calls[0].url).toBe('/v1/course-approval-requests?course_id=course%2Fwith%20spaces');
  });

  it('uses the ordinary account for all ordinary reviewer writes and ignores a stale capability', async () => {
    authMocks.getAccessToken.mockReturnValue('methodologist-token');
    sessionStorage.setItem('course_review_token', 'unrelated-stale-capability');
    await startReviewAttempt('request-1');
    await saveReviewProgress('attempt-1', 1, 0, 'in_progress');
    await submitReviewTest('attempt-1', []);
    await submitReviewDecision('attempt-1', 'approve', null, true);
    expect(calls).toHaveLength(4);
    expect(calls.every((call) => call.authorization === 'Bearer methodologist-token')).toBe(true);
  });

  it('refreshes an expired ordinary reviewer session once and retries with its refreshed token', async () => {
    authMocks.getAccessToken.mockReturnValue('expired-methodologist-token');
    authMocks.forceRefreshAndStoreSession.mockImplementation(async () => {
      authMocks.getAccessToken.mockReturnValue('refreshed-methodologist-token');
      return true;
    });
    const adapter = api.defaults.adapter as AxiosAdapter;
    let first = true;
    api.defaults.adapter = async (config) => {
      if (first) {
        first = false;
        throw new AxiosError('Expired', 'ERR_BAD_REQUEST', config, undefined, { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config });
      }
      return await adapter(config);
    };
    await startReviewAttempt('request-1');
    expect(authMocks.forceRefreshAndStoreSession).toHaveBeenCalledTimes(1);
    expect(calls).toEqual([{ url: '/v1/course-approval-requests/request-1/attempts', authorization: 'Bearer refreshed-methodologist-token' }]);
  });

  it('never falls back to the signed-in account or refreshes a rejected review capability', async () => {
    authMocks.getAccessToken.mockReturnValue('methodologist-token');
    api.defaults.adapter = async (config) => {
      const authorization = config.headers.get('Authorization');
      expect(authorization).toBe('Bearer invalid-scoped-token');
      throw new AxiosError('Revoked', 'ERR_BAD_REQUEST', config, undefined, { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config });
    };
    await expect(startReviewAttempt('request-1', 'invalid-scoped-token')).rejects.toMatchObject({ response: { status: 401 } });
    expect(authMocks.forceRefreshAndStoreSession).not.toHaveBeenCalled();
  });

  it('keeps capability-only reads anonymous when no capability is present', async () => {
    await getScopedReviewRequest(undefined, 'request-1');
    expect(calls[0].authorization).toBeUndefined();
  });

  it.each(['same-actor-relogin', 'actor-switch', 'role-switch'])('does not replay an old review write after %s during refresh', async (replacement) => {
    let finishRefresh: (value: boolean) => void = () => undefined;
    authMocks.forceRefreshAndStoreSession.mockImplementation(() => new Promise<boolean>((resolve) => { finishRefresh = resolve; }));
    api.defaults.adapter = async (config) => {
      calls.push({ url: config.url, authorization: config.headers.get('Authorization') as string });
      throw new AxiosError('Expired', 'ERR_BAD_REQUEST', config, undefined, { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config });
    };
    const pending = submitReviewDecision('attempt-1', 'approve', null, true);
    const rejected = expect(pending).rejects.toMatchObject({ code: 'ERR_CANCELED' });
    await vi.waitFor(() => expect(authMocks.forceRefreshAndStoreSession).toHaveBeenCalledTimes(1));
    if (replacement === 'same-actor-relogin') authMocks.getAuthSessionEpoch.mockReturnValue(2);
    if (replacement === 'actor-switch') authMocks.getCurrentUser.mockReturnValue({ user_id: 'reviewer-2', tenant_id: 'tenant-2', role: 'methodologist' });
    if (replacement === 'role-switch') authMocks.getCurrentUser.mockReturnValue({ user_id: 'reviewer-1', tenant_id: 'tenant-1', role: 'student' });
    authMocks.getAccessToken.mockReturnValue('replacement-token');
    finishRefresh(true);
    await rejected;
    expect(calls).toHaveLength(1);
    expect(authMocks.clearStoredAuth).not.toHaveBeenCalled();
  });

  it('does not dispatch ordinary reviewer writes from an unrelated active role', async () => {
    authMocks.getCurrentUser.mockReturnValue({ user_id: 'reviewer-1', tenant_id: 'tenant-1', role: 'student' });
    await expect(startReviewAttempt('request-1')).rejects.toMatchObject({ code: 'ERR_CANCELED' });
    expect(calls).toHaveLength(0);
  });

  it('rejects a late successful response after same-actor session replacement', async () => {
    const adapter = api.defaults.adapter as AxiosAdapter;
    let resolveResponse: (() => void) | undefined;
    api.defaults.adapter = async (config) => {
      await new Promise<void>((resolve) => { resolveResponse = resolve; });
      return adapter(config);
    };
    const pending = startReviewAttempt('request-1');
    const rejected = expect(pending).rejects.toMatchObject({ code: 'ERR_CANCELED' });
    await vi.waitFor(() => expect(resolveResponse).toBeTypeOf('function'));
    authMocks.getAuthSessionEpoch.mockReturnValue(2);
    resolveResponse!();
    await rejected;
  });

  it('preserves a replacement session when it changes while the authenticated retry is pending', async () => {
    authMocks.forceRefreshAndStoreSession.mockResolvedValue(true);
    const adapter = api.defaults.adapter as AxiosAdapter;
    let resolveResponse: (() => void) | undefined;
    let count = 0;
    api.defaults.adapter = async (config) => {
      count += 1;
      if (count === 1) throw new AxiosError('Expired', 'ERR_BAD_REQUEST', config, undefined, { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config });
      await new Promise<void>((resolve) => { resolveResponse = resolve; });
      return adapter(config);
    };
    const pending = startReviewAttempt('request-1');
    const rejected = expect(pending).rejects.toMatchObject({ code: 'ERR_CANCELED' });
    await vi.waitFor(() => expect(resolveResponse).toBeTypeOf('function'));
    authMocks.getAuthSessionEpoch.mockReturnValue(2);
    resolveResponse!();
    await rejected;
    expect(authMocks.clearStoredAuth).not.toHaveBeenCalled();
  });
});
