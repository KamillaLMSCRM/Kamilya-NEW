import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useGenerationWorkflow } from '@/features/ai-generation/useGenerationWorkflow';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));

const activeJob = {
  id: 'current-tenant-job', status: 'running', course_id: 'draft-course',
  created_at: '2026-08-30T08:00:00Z', updated_at: '2026-08-30T08:01:00Z',
  progress: 40, stage: 'content_generation', message: '', queue_position: null,
  estimated_wait_seconds: null, tenant_active_jobs: 1, tenant_active_limit: 1,
};

describe('AI generation workflow recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('recovers the current tenant job after a stale impersonation job id returns 404', async () => {
    localStorage.setItem('ai_active_job_id', 'stale-other-tenant-job');
    apiMock.get
      .mockRejectedValueOnce({ response: { status: 404 } })
      .mockResolvedValueOnce({ data: [activeJob] });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });

    await waitFor(() => expect(result.current.currentJob?.id).toBe('current-tenant-job'));
    expect(result.current.step).toBe('generate');
    expect(localStorage.getItem('ai_active_job_id')).toBe('current-tenant-job');
    expect(apiMock.get).toHaveBeenNthCalledWith(2, '/v1/ai/jobs');
  });
});
