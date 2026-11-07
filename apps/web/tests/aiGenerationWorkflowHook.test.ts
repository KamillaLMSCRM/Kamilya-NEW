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
  it('continues the same held job only when a retained-response capability is present', async () => {
    const held = { ...activeJob, status: 'reconciliation_required', stage: 'interrupted', course_id: null, retained_response_replay_available: true };
    const pending = { ...held, status: 'pending', stage: 'queued', retained_response_replay_available: false };
    apiMock.post.mockResolvedValueOnce({ data: pending });
    const { result } = renderHook(() => useGenerationWorkflow());
    act(() => { result.current.startJob({ ...held, retained_response_replay_available: false }); });
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).not.toHaveBeenCalled();
    act(() => { result.current.startJob(held); });
    await act(async () => { await result.current.resumeJob(); });
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.post).toHaveBeenCalledWith('/v1/ai/jobs/current-tenant-job/resume');
    expect(result.current.currentJob?.status).toBe('pending');
  });

  it('keeps an unknown retained-response dispatch fenced after capability disappears', async () => {
    const held = { ...activeJob, status: 'reconciliation_required', stage: 'interrupted', course_id: null, retained_response_replay_available: true };
    const unknown = { ...held, retained_response_replay_available: false };
    apiMock.post.mockRejectedValueOnce(new Error('connection lost'));
    apiMock.get.mockResolvedValue({ data: unknown });
    const { result } = renderHook(() => useGenerationWorkflow());
    act(() => { result.current.startJob(held); });
    await act(async () => { await result.current.resumeJob(); });
    await act(async () => { await result.current.resumeJob(); });
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.get).toHaveBeenCalledTimes(3);
    expect(apiMock.get).toHaveBeenCalledWith('/v1/ai/jobs/current-tenant-job');
    expect(result.current.resumeReconciliation).toBe(true);
  });

  it('keeps a held HTTP200 resume response fenced until exact status is known', async () => {
    const held = { ...activeJob, status: 'reconciliation_required', stage: 'interrupted', course_id: null, retained_response_replay_available: true };
    apiMock.post.mockResolvedValueOnce({ data: held });
    apiMock.get.mockResolvedValueOnce({ data: held });
    const { result } = renderHook(() => useGenerationWorkflow());
    act(() => { result.current.startJob(held); });
    await act(async () => { await result.current.resumeJob(); });
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    expect(result.current.resumeReconciliation).toBe(true);
  });

  it('ignores an unresolved explicit restore after a new job starts', async () => {
    let resolve!: (value: { data: typeof activeJob }) => void;
    apiMock.get.mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
    const { result } = renderHook(() => useGenerationWorkflow(null, 'old-job'));
    let restore!: Promise<void>;
    act(() => { restore = result.current.restoreActiveJob(); });
    act(() => { result.current.startJob(activeJob); });
    await act(async () => { resolve({ data: { ...activeJob, id: 'old-job' } }); await restore; });
    expect(result.current.currentJob?.id).toBe(activeJob.id);
    expect(localStorage.getItem('ai_active_job_id')).toBe(activeJob.id);
  });
  it('does not reconcile an old unknown resume after a different job is selected', async () => {
    const interrupted = { ...activeJob, id: 'old-interrupted', status: 'interrupted', job_type: 'course_generation' };
    let rejectPost!: (error: unknown) => void;
    apiMock.get.mockResolvedValueOnce({ data: [interrupted] });
    apiMock.post.mockReturnValueOnce(new Promise((_, reject) => { rejectPost = reject; }));
    const { result } = renderHook(() => useGenerationWorkflow());
    await act(async () => { await result.current.restoreActiveJob(); });
    let resume!: Promise<unknown>;
    await act(async () => { resume = result.current.resumeJob(); await Promise.resolve(); });
    act(() => { result.current.startJob(activeJob); });
    await act(async () => { rejectPost({ response: { status: 503 } }); await resume; });
    expect(result.current.currentJob?.id).toBe(activeJob.id);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.get.mock.calls.filter(([url]) => url === '/v1/ai/jobs/old-interrupted')).toHaveLength(0);
  });
  it('ignores an old status response after a different job is selected', async () => {
    let resolve!: (value: { data: typeof activeJob }) => void;
    const old = { ...activeJob, id: 'old-job' };
    apiMock.get.mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
    const { result } = renderHook(() => useGenerationWorkflow());
    act(() => { result.current.startJob(old); });
    let read!: Promise<void>;
    act(() => { read = result.current.refreshJob(); });
    act(() => { result.current.startJob(activeJob); });
    await act(async () => { resolve({ data: old }); await read; });
    expect(result.current.currentJob?.id).toBe(activeJob.id);
  });
  beforeEach(() => {
    vi.resetAllMocks();
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
    expect(apiMock.get).toHaveBeenNthCalledWith(2, '/v1/ai/jobs?scope=mine');
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

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/ai/jobs?scope=mine'));
    expect(result.current.currentJob).toBeNull();
    expect(result.current.step).toBe('documents');
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
  });

  it('restores an explicit failed job from the dashboard link without starting generation', async () => {
    const failedJob = {
      ...activeJob,
      id: 'failed-course-job',
      job_type: 'course_generation',
      course_id: null,
      status: 'failed',
      stage: 'review',
      message: 'generation failed',
    };
    apiMock.get.mockResolvedValueOnce({ data: failedJob });
    const { result } = renderHook(() => useGenerationWorkflow(null, 'failed-course-job'));

    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.currentJob?.id).toBe('failed-course-job');
    expect(result.current.step).toBe('generate');
    expect(apiMock.get).toHaveBeenCalledWith('/v1/ai/jobs/failed-course-job');
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
  });

  it('does not let an already-applied explicit job replace a newly started job', async () => {
    const failedJob = {
      ...activeJob,
      id: 'failed-course-job',
      job_type: 'course_generation',
      status: 'failed',
      stage: 'review',
    };
    apiMock.get.mockResolvedValueOnce({ data: failedJob });
    const { result } = renderHook(() => useGenerationWorkflow(null, 'failed-course-job'));

    await act(async () => { await result.current.restoreActiveJob(); });
    expect(result.current.currentJob?.id).toBe('failed-course-job');

    act(() => { result.current.startJob(activeJob); });
    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.currentJob?.id).toBe('current-tenant-job');
    expect(apiMock.get).toHaveBeenCalledTimes(1);
  });

  it('explains a missing explicit job while keeping ordinary recovery available', async () => {
    apiMock.get
      .mockRejectedValueOnce({ response: { status: 404 } })
      .mockResolvedValueOnce({ data: [activeJob] });
    const { result } = renderHook(() => useGenerationWorkflow(null, 'missing-job'));

    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.requestedJobMissing).toBe(true);
    expect(result.current.currentJob?.id).toBe('current-tenant-job');
    expect(result.current.step).toBe('generate');
  });

  it('clears the missing explicit-job notice when the query is dismissed', async () => {
    apiMock.get
      .mockRejectedValueOnce({ response: { status: 404 } })
      .mockResolvedValueOnce({ data: [activeJob] });
    const { result, rerender } = renderHook(
      ({ jobId }: { jobId: string | null }) => useGenerationWorkflow(null, jobId),
      { initialProps: { jobId: 'missing-job' as string | null } },
    );

    await act(async () => { await result.current.restoreActiveJob(); });
    expect(result.current.requestedJobMissing).toBe(true);

    rerender({ jobId: null });

    await waitFor(() => expect(result.current.requestedJobMissing).toBe(false));
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

  it('supersedes a persisted interrupted job with a newer live job from scoped discovery', async () => {
    const interruptedJob = { ...activeJob, id: 'old-interrupted-job', status: 'interrupted', stage: 'interrupted', job_type: 'course_generation' };
    const liveJob = { ...activeJob, id: 'new-live-job', created_at: '2026-08-30T09:00:00Z', status: 'running' };
    localStorage.setItem('ai_active_job_id', interruptedJob.id);
    apiMock.get.mockResolvedValueOnce({ data: interruptedJob }).mockResolvedValueOnce({ data: [interruptedJob, liveJob] });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.currentJob?.id).toBe(liveJob.id);
    expect(result.current.currentJob?.status).toBe('running');
    expect(localStorage.getItem('ai_active_job_id')).toBe(liveJob.id);
    expect(apiMock.get).toHaveBeenNthCalledWith(2, '/v1/ai/jobs?scope=mine');
  });

  it('keeps the persisted interrupted job when live discovery is unavailable', async () => {
    const interruptedJob = { ...activeJob, id: 'old-interrupted-job', status: 'interrupted', stage: 'interrupted', job_type: 'course_generation' };
    localStorage.setItem('ai_active_job_id', interruptedJob.id);
    apiMock.get.mockResolvedValueOnce({ data: interruptedJob }).mockRejectedValueOnce(new Error('list unavailable'));
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.currentJob?.id).toBe(interruptedJob.id);
    expect(result.current.currentJob?.status).toBe('interrupted');
  });

  it('supersedes a persisted reconciliation hold with a newer executing job', async () => {
    const heldJob = { ...activeJob, id: 'old-held-job', status: 'reconciliation_required', stage: 'interrupted', job_type: 'course_generation' };
    const liveJob = { ...activeJob, id: 'new-live-job', created_at: '2026-08-30T09:00:00Z', status: 'running' };
    localStorage.setItem('ai_active_job_id', heldJob.id);
    apiMock.get.mockResolvedValueOnce({ data: heldJob }).mockResolvedValueOnce({ data: [heldJob, liveJob] });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.currentJob?.id).toBe(liveJob.id);
    expect(result.current.currentJob?.status).toBe('running');
    expect(localStorage.getItem('ai_active_job_id')).toBe(liveJob.id);
    expect(apiMock.get).toHaveBeenNthCalledWith(2, '/v1/ai/jobs?scope=mine');
  });

  it('keeps a persisted reconciliation hold when discovery finds no executing job', async () => {
    const heldJob = { ...activeJob, id: 'old-held-job', status: 'reconciliation_required', stage: 'interrupted', job_type: 'course_generation' };
    localStorage.setItem('ai_active_job_id', heldJob.id);
    apiMock.get.mockResolvedValueOnce({ data: heldJob }).mockResolvedValueOnce({ data: [heldJob] });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.currentJob?.id).toBe(heldJob.id);
    expect(result.current.currentJob?.status).toBe('reconciliation_required');
    expect(localStorage.getItem('ai_active_job_id')).toBe(heldJob.id);
  });

  it('keeps a persisted reconciliation hold when discovery fails', async () => {
    const heldJob = { ...activeJob, id: 'old-held-job', status: 'reconciliation_required', stage: 'interrupted', job_type: 'course_generation' };
    localStorage.setItem('ai_active_job_id', heldJob.id);
    apiMock.get.mockResolvedValueOnce({ data: heldJob }).mockRejectedValueOnce(new Error('list unavailable'));
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });

    expect(result.current.currentJob?.id).toBe(heldJob.id);
    expect(result.current.currentJob?.status).toBe('reconciliation_required');
    expect(localStorage.getItem('ai_active_job_id')).toBe(heldJob.id);
  });

  it('ignores a delayed interrupted-job discovery after the request scope changes', async () => {
    const interruptedJob = { ...activeJob, id: 'old-interrupted-job', status: 'interrupted', stage: 'interrupted', job_type: 'course_generation' };
    const liveJob = { ...activeJob, id: 'new-live-job', status: 'running' };
    let scopeKey = 'actor-a/source-a';
    let resolveList!: (value: unknown) => void;
    localStorage.setItem('ai_active_job_id', interruptedJob.id);
    apiMock.get.mockResolvedValueOnce({ data: interruptedJob })
      .mockReturnValueOnce(new Promise((resolve) => { resolveList = resolve; }));
    const { result } = renderHook(() => useGenerationWorkflow(null, () => scopeKey));
    let restore!: Promise<unknown>;
    await act(async () => {
      restore = result.current.restoreActiveJob();
      await Promise.resolve();
    });
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(2));
    scopeKey = 'actor-b/source-b';
    await act(async () => {
      resolveList({ data: [interruptedJob, liveJob] });
      await restore;
    });
    expect(result.current.currentJob).toBeNull();
    expect(localStorage.getItem('ai_active_job_id')).toBe(interruptedJob.id);
  });

  it('ignores a delayed interrupted-job discovery after unmount', async () => {
    const interruptedJob = { ...activeJob, id: 'old-interrupted-job', status: 'interrupted', stage: 'interrupted', job_type: 'course_generation' };
    const liveJob = { ...activeJob, id: 'new-live-job', status: 'running' };
    let resolveList!: (value: unknown) => void;
    localStorage.setItem('ai_active_job_id', interruptedJob.id);
    apiMock.get.mockResolvedValueOnce({ data: interruptedJob })
      .mockReturnValueOnce(new Promise((resolve) => { resolveList = resolve; }));
    const { result, unmount } = renderHook(() => useGenerationWorkflow());
    let restore!: Promise<unknown>;
    await act(async () => {
      restore = result.current.restoreActiveJob();
      await Promise.resolve();
    });
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(2));
    unmount();
    await act(async () => {
      resolveList({ data: [interruptedJob, liveJob] });
      await restore;
    });
    expect(result.current.currentJob).toBeNull();
    expect(localStorage.getItem('ai_active_job_id')).toBe(interruptedJob.id);
  });

  it('keeps recovery callback identity stable across equivalent inline scope callbacks', async () => {
    apiMock.get.mockResolvedValueOnce({ data: [] });
    const { result, rerender } = renderHook(({ scope }: { scope: string }) =>
      useGenerationWorkflow(null, () => scope), { initialProps: { scope: 'actor-a/source-a' } });
    const restore = result.current.restoreActiveJob;

    await act(async () => { await restore(); });
    rerender({ scope: 'actor-a/source-a' });

    expect(result.current.restoreActiveJob).toBe(restore);
    expect(apiMock.get).toHaveBeenCalledTimes(1);
  });

  it('reconciles unknown resume dispatch by exact GET and never posts twice while pending', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    const pendingJob = { ...interruptedJob, status: 'pending', stage: 'queued' };
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] })
      .mockResolvedValueOnce({ data: pendingJob })
      .mockResolvedValueOnce({ data: pendingJob });
    apiMock.post.mockRejectedValueOnce({ response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: interruptedJob.id } } } });
    const { result } = renderHook(() => useGenerationWorkflow());
    await act(async () => { await result.current.restoreActiveJob(); });
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(result.current.currentJob?.status).toBe('pending');
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${interruptedJob.id}`).length).toBe(1);
  });

  it('keeps unknown resume outcome fenced when exact GET fails or returns another id', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] }).mockRejectedValueOnce(new Error('read failed'));
    apiMock.post.mockRejectedValueOnce(new Error('network lost'));
    const { result } = renderHook(() => useGenerationWorkflow());
    await act(async () => { await result.current.restoreActiveJob(); });
    await expect(act(async () => { await result.current.resumeJob(); })).rejects.toThrow('read failed');
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    apiMock.get.mockResolvedValueOnce({ data: [{ ...interruptedJob, id: 'foreign-job' }] });
    await expect(act(async () => { await result.current.resumeJob(); })).rejects.toThrow('resume_job_identity_mismatch');
    expect(apiMock.post).toHaveBeenCalledTimes(1);
  });

  it('does not dispatch a late reconciliation result after the workflow unmounts', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    const pendingJob = { ...interruptedJob, status: 'pending', stage: 'queued' };
    let resolveRead!: (value: unknown) => void;
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] })
      .mockReturnValueOnce(new Promise((resolve) => { resolveRead = resolve; }));
    apiMock.post.mockRejectedValueOnce({ response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: interruptedJob.id } } } });
    const { result, unmount } = renderHook(() => useGenerationWorkflow());
    await act(async () => { await result.current.restoreActiveJob(); });
    let reconciliation!: Promise<unknown>;
    await act(async () => {
      reconciliation = result.current.resumeJob();
      await Promise.resolve();
    });
    unmount();
    await act(async () => {
      resolveRead({ data: pendingJob });
      await reconciliation;
    });
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${interruptedJob.id}`).length).toBe(1);
  });

  it('ignores a late reconciliation result after the actor scope changes', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    const pendingJob = { ...interruptedJob, status: 'pending', stage: 'queued' };
    let scopeKey = 'actor-a/source-a';
    let resolveRead!: (value: unknown) => void;
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] })
      .mockReturnValueOnce(new Promise((resolve) => { resolveRead = resolve; }));
    apiMock.post.mockRejectedValueOnce({ response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: interruptedJob.id } } } });
    const { result } = renderHook(() => useGenerationWorkflow(null, () => scopeKey));
    await act(async () => { await result.current.restoreActiveJob(); });
    let reconciliation!: Promise<unknown>;
    await act(async () => {
      reconciliation = result.current.resumeJob();
      await Promise.resolve();
    });
    scopeKey = 'actor-b/source-b';
    await act(async () => {
      resolveRead({ data: pendingJob });
      await reconciliation;
    });
    expect(result.current.currentJob?.status).toBe('interrupted');
    expect(apiMock.post).toHaveBeenCalledTimes(1);
  });

  it('does not start a GET when an unknown resume POST rejects after unmount', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    let rejectPost!: (error: unknown) => void;
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] });
    apiMock.post.mockReturnValueOnce(new Promise((_, reject) => { rejectPost = reject; }));
    const { result, unmount } = renderHook(() => useGenerationWorkflow());
    await act(async () => { await result.current.restoreActiveJob(); });
    let resume!: Promise<unknown>;
    await act(async () => {
      resume = result.current.resumeJob();
      await Promise.resolve();
    });
    unmount();
    await act(async () => {
      rejectPost({ response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: interruptedJob.id } } } });
      await resume;
    });
    expect(apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${interruptedJob.id}`).length).toBe(0);
  });

  it('does not start a GET when an unknown resume POST settles after the actor scope changes', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    let scopeKey = 'actor-a/source-a';
    let rejectPost!: (error: unknown) => void;
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] });
    apiMock.post.mockReturnValueOnce(new Promise((_, reject) => { rejectPost = reject; }));
    const { result } = renderHook(() => useGenerationWorkflow(null, () => scopeKey));
    await act(async () => { await result.current.restoreActiveJob(); });
    let resume!: Promise<unknown>;
    await act(async () => {
      resume = result.current.resumeJob();
      await Promise.resolve();
    });
    scopeKey = 'actor-b/source-b';
    await act(async () => {
      rejectPost({ response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: interruptedJob.id } } } });
      await resume;
    });
    expect(apiMock.get.mock.calls.filter(([url]) => url === `/v1/ai/jobs/${interruptedJob.id}`).length).toBe(0);
  });

  it('clears the resume fence after confirmed pending state so a later interruption can resume once', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    const pendingJob = { ...interruptedJob, status: 'pending', stage: 'queued' };
    const interruptedAgain = { ...interruptedJob, progress: 55 };
    apiMock.get.mockResolvedValueOnce({ data: [interruptedJob] }).mockResolvedValueOnce({ data: interruptedAgain });
    apiMock.post.mockResolvedValueOnce({ data: pendingJob }).mockResolvedValueOnce({ data: pendingJob });
    const { result } = renderHook(() => useGenerationWorkflow());
    await act(async () => { await result.current.restoreActiveJob(); });
    await act(async () => { await result.current.resumeJob(); });
    await act(async () => { await result.current.refreshJob(); });
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledTimes(2);
  });

  it('clears the unknown fence after a read-only running state and permits a later interruption resume', async () => {
    const interruptedJob = { ...activeJob, status: 'interrupted', job_type: 'course_generation' };
    const runningJob = { ...interruptedJob, status: 'running', stage: 'content_generation' };
    const pendingJob = { ...interruptedJob, status: 'pending', stage: 'queued' };
    apiMock.get
      .mockResolvedValueOnce({ data: [interruptedJob] })
      .mockResolvedValueOnce({ data: interruptedJob })
      .mockResolvedValueOnce({ data: runningJob })
      .mockResolvedValueOnce({ data: interruptedJob });
    apiMock.post
      .mockRejectedValueOnce({ response: { status: 503, data: { detail: { code: 'ai_job_dispatch_outcome_unknown', job_id: interruptedJob.id } } } })
      .mockResolvedValueOnce({ data: pendingJob });
    const { result } = renderHook(() => useGenerationWorkflow());
    await act(async () => { await result.current.restoreActiveJob(); });
    await act(async () => { await result.current.resumeJob(); });
    await act(async () => { await result.current.resumeJob(); });
    expect(result.current.currentJob?.status).toBe('running');
    await act(async () => { await result.current.refreshJob(); });
    expect(result.current.currentJob?.status).toBe('interrupted');
    await act(async () => { await result.current.resumeJob(); });
    expect(apiMock.post).toHaveBeenCalledTimes(2);
    expect(apiMock.post).toHaveBeenLastCalledWith('/v1/ai/jobs/current-tenant-job/resume');
  });

  it('does not restore a completed workflow from a previous visit', async () => {
    const completedJob = { ...activeJob, status: 'completed', stage: 'completed', progress: 100 };
    localStorage.setItem('ai_active_job_id', completedJob.id);
    localStorage.setItem('ai_generation_workflow_context', JSON.stringify({
      job_id: completedJob.id,
      program_id: 'program-1',
    }));
    apiMock.get.mockResolvedValueOnce({ data: completedJob });
    const { result } = renderHook(() => useGenerationWorkflow());

    await act(async () => { await result.current.restoreActiveJob(); });
    expect(result.current.currentJob).toBeNull();
    expect(result.current.step).toBe('documents');
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
    expect(localStorage.getItem('ai_generation_workflow_context')).toBeNull();
  });

  it('keeps a just-completed job in the current session but clears restoration state', async () => {
    const completedJob = { ...activeJob, status: 'completed', stage: 'completed', progress: 100 };
    localStorage.setItem('ai_active_job_id', activeJob.id);
    localStorage.setItem('ai_generation_workflow_context', JSON.stringify({
      job_id: activeJob.id,
      program_id: 'program-1',
    }));
    apiMock.get.mockResolvedValueOnce({ data: completedJob });
    const { result } = renderHook(() => useGenerationWorkflow());

    act(() => { result.current.startJob(activeJob); });
    await act(async () => { await result.current.refreshJob(); });

    expect(result.current.currentJob?.status).toBe('completed');
    expect(result.current.step).toBe('review');
    expect(localStorage.getItem('ai_active_job_id')).toBeNull();
    expect(localStorage.getItem('ai_generation_workflow_context')).toBeNull();
  });

  it('allows an existing-job view to clear requested and inherited program context', () => {
    const { result } = renderHook(() => useGenerationWorkflow('requested-program'));

    act(() => { result.current.startJob(activeJob); });
    expect(result.current.programId).toBe('requested-program');
    expect(JSON.parse(localStorage.getItem('ai_generation_workflow_context') || '{}').program_id).toBe('requested-program');

    act(() => { result.current.startJob(activeJob, { programId: 'inherited-program' }); });
    expect(result.current.programId).toBe('inherited-program');
    act(() => { result.current.startJob(activeJob, { programId: null }); });
    expect(result.current.programId).toBeNull();
    expect(JSON.parse(localStorage.getItem('ai_generation_workflow_context') || '{}').program_id).toBeNull();
  });
});
