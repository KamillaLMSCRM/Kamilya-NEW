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

  it('keeps a new generation form on documents when only a failed job exists', async () => {
    const failedJob = {
      ...activeJob,
      id: 'failed-course-job',
      job_type: 'course_generation',
      course_id: null,
      status: 'failed',
      stage: 'failed',
      message: 'SoftTimeLimitExceeded: generation failed',
    };
    apiMock.get.mockResolvedValueOnce({ data: [failedJob] });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/ai/jobs'));
    expect(result.current.currentJob).toBeNull();
    expect(result.current.step).toBe('documents');
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
  });

  it('restores and resumes an interrupted generation with the same job id', async () => {
    const interruptedJob = {
      ...activeJob,
      status: 'interrupted',
      stage: 'interrupted',
      progress: 54,
      job_type: 'course_generation',
    };
    const pendingJob = { ...interruptedJob, status: 'pending', stage: 'queued' };
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] });
    apiMock.post.mockResolvedValueOnce({ data: pendingJob });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });
    expect(result.current.currentJob?.status).toBe('interrupted');
    expect(result.current.step).toBe('generate');

    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/jobs/current-tenant-job/resume');
    expect(result.current.currentJob?.id).toBe('current-tenant-job');
    expect(result.current.currentJob?.status).toBe('pending');
  });

  it('clears a restored completed workflow when starting a new course', async () => {
    const completedJob = { ...activeJob, status: 'completed', stage: 'completed', progress: 100 };
    localStorage.setItem('ai_active_job_id', completedJob.id);
    localStorage.setItem('ai_generation_workflow_context', JSON.stringify({
      job_id: completedJob.id,
      program_id: 'program-1',
    }));
    apiMock.get.mockResolvedValueOnce({ data: completedJob });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });
    expect(result.current.step).toBe('review');

    act(() => { result.current.resetWorkflow(); });

    expect(result.current.currentJob).toBeNull();
    expect(result.current.step).toBe('documents');
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
    expect(localStorage.getItem('ai_generation_workflow_context')).toBeNull();
  });
});
