import type { InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  clearStoredAuth: vi.fn(),
  getAccessToken: vi.fn(() => 'learner-token'),
  forceRefreshAndStoreSession: vi.fn(),
}));
vi.mock('@/lib/auth', () => authMocks);

import { api } from '@/lib/api';
import { getScopedReviewRequest, listApprovalRequests, startReviewAttempt, verifyReviewPin } from '@/lib/courseApproval';

describe('scoped review transport', () => {
  const originalAdapter = api.defaults.adapter;
  const calls: Array<{ url?: string; authorization?: string }> = [];

  beforeEach(() => {
    calls.length = 0;
    sessionStorage.clear();
    authMocks.getAccessToken.mockReturnValue('learner-token');
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
        return { data: { attempt_id: 'attempt-1', revision_id: 'revision-1', snapshot_sha256: 'sha256', activity_state: 'not_started', snapshot: { schema_version: 1, release_version: 1, course: { id: 'course-1', title: 'Course' }, modules: [] } }, status: 200, statusText: 'OK', headers: {}, config: config as InternalAxiosRequestConfig };
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
});
