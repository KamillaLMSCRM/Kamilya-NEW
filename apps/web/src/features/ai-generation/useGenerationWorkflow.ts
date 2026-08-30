'use client';

import { useCallback, useEffect, useReducer } from 'react';
import { api } from '@/lib/api';
import { selectOldestActiveCourseJob, type AIGenerationJob } from '@/lib/aiGenerationJobs';
import {
  generationWorkflowReducer,
  initialGenerationWorkflowState,
  type GenerationWorkflowAction,
} from './generationWorkflow';

const activeJobStorageKey = 'ai_active_job_id';
const isActive = (job: AIGenerationJob) => job.status === 'pending' || job.status === 'running';

function actionForPolledJob(job: AIGenerationJob): GenerationWorkflowAction {
  if (job.status === 'completed') return { type: 'job_completed', job };
  if (job.status === 'failed' || job.status === 'cancelled') return { type: 'job_terminal', job };
  return { type: 'job_active', job };
}

export function useGenerationWorkflow() {
  const [state, dispatch] = useReducer(generationWorkflowReducer, initialGenerationWorkflowState);

  const restoreFromJobList = useCallback(async () => {
    const response = await api.get<AIGenerationJob[]>('/v1/ai/jobs');
    const activeJob = selectOldestActiveCourseJob(response.data);
    if (!activeJob) return;
    localStorage.setItem(activeJobStorageKey, activeJob.id);
    dispatch({ type: 'job_active', job: activeJob });
  }, []);

  const restoreActiveJob = useCallback(async () => {
    const savedJobId = localStorage.getItem(activeJobStorageKey);
    if (!savedJobId) {
      try {
        await restoreFromJobList();
      } catch {
        // A missing list is non-blocking; the page remains usable for a new job.
      }
      return;
    }

    try {
      const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${savedJobId}`);
      const job = response.data;
      if (isActive(job)) dispatch({ type: 'job_active', job });
      else if (job.status === 'completed' && job.course_id) dispatch({ type: 'job_completed', job });
      else if (job.status === 'failed' || job.status === 'cancelled') dispatch({ type: 'job_terminal', job });
      if (!isActive(job)) localStorage.removeItem(activeJobStorageKey);
    } catch (error: any) {
      // An impersonation/tenant switch can leave a stale id. On a confirmed
      // 404, clear it and immediately discover the active job in this tenant.
      if (error?.response?.status === 404) {
        localStorage.removeItem(activeJobStorageKey);
        try {
          await restoreFromJobList();
        } catch {
          // The job list is optional recovery; keep the page usable.
        }
      }
    }
  }, [restoreFromJobList]);

  const startJob = useCallback((job: AIGenerationJob) => {
    localStorage.setItem(activeJobStorageKey, job.id);
    dispatch({ type: 'job_started', job });
  }, []);

  const refreshJob = useCallback(async () => {
    if (!state.currentJob) return;
    const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${state.currentJob.id}`);
    const job = response.data;
    dispatch(actionForPolledJob(job));
    if (!isActive(job)) localStorage.removeItem(activeJobStorageKey);
  }, [state.currentJob]);

  const cancelJob = useCallback(async () => {
    if (!state.currentJob) return;
    await api.post(`/v1/ai/jobs/${state.currentJob.id}/cancel`);
    localStorage.removeItem(activeJobStorageKey);
    dispatch({ type: 'job_cleared' });
  }, [state.currentJob]);

  const prepareRetry = useCallback(() => {
    localStorage.removeItem(activeJobStorageKey);
    dispatch({ type: 'job_cleared' });
  }, []);

  useEffect(() => {
    const job = state.currentJob;
    if (!job || !isActive(job)) return;
    const interval = window.setInterval(() => {
      void refreshJob().catch(() => {
        // Keep polling through transient network failures.
      });
    }, 3000);
    return () => window.clearInterval(interval);
  }, [refreshJob, state.currentJob]);

  return {
    ...state,
    restoreActiveJob,
    startJob,
    refreshJob,
    cancelJob,
    prepareRetry,
  };
}
