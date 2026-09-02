'use client';

import { useCallback, useEffect, useReducer } from 'react';
import { api } from '@/lib/api';
import {
  selectOldestActiveCourseJob,
  type AIGenerationJob,
  type AIGenerationWorkflowContext,
} from '@/lib/aiGenerationJobs';
import {
  generationWorkflowReducer,
  initialGenerationWorkflowState,
  type GenerationWorkflowAction,
} from './generationWorkflow';

const activeJobStorageKey = 'ai_active_job_id';
const workflowContextStorageKey = 'ai_generation_workflow_context';
const isActive = (job: AIGenerationJob) => job.status === 'pending' || job.status === 'running';

function readWorkflowContext(): AIGenerationWorkflowContext | null {
  const raw = localStorage.getItem(workflowContextStorageKey);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<AIGenerationWorkflowContext>;
    if (typeof value.job_id !== 'string' || !value.job_id) return null;
    return {
      job_id: value.job_id,
      program_id: typeof value.program_id === 'string' && value.program_id.trim() ? value.program_id : null,
    };
  } catch {
    return null;
  }
}

function persistWorkflowContext(jobId: string, programId: string | null) {
  localStorage.setItem(workflowContextStorageKey, JSON.stringify({ job_id: jobId, program_id: programId }));
}

function clearWorkflowContext() {
  localStorage.removeItem(workflowContextStorageKey);
}

function actionForPolledJob(job: AIGenerationJob): GenerationWorkflowAction {
  if (job.status === 'completed') return { type: 'job_completed', job };
  if (job.status === 'failed' || job.status === 'cancelled') return { type: 'job_terminal', job };
  return { type: 'job_active', job };
}

export function useGenerationWorkflow(requestedProgramId: string | null = null) {
  const [state, dispatch] = useReducer(generationWorkflowReducer, initialGenerationWorkflowState);

  const restoreFromJobList = useCallback(async () => {
    const response = await api.get<AIGenerationJob[]>('/v1/ai/jobs');
    const activeJob = selectOldestActiveCourseJob(response.data);
    if (activeJob) {
      const savedContext = readWorkflowContext();
      const programId = savedContext?.job_id === activeJob.id ? savedContext.program_id : null;
      localStorage.setItem(activeJobStorageKey, activeJob.id);
      persistWorkflowContext(activeJob.id, programId);
      dispatch({ type: 'job_restored', job: activeJob, programId });
      return;
    }
    localStorage.removeItem(activeJobStorageKey);
    clearWorkflowContext();
    dispatch({ type: 'job_cleared' });
  }, []);

  const restoreActiveJob = useCallback(async () => {
    const savedContext = readWorkflowContext();
    const savedJobId = localStorage.getItem(activeJobStorageKey) || savedContext?.job_id;
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
      const programId = savedContext?.job_id === job.id ? savedContext.program_id : null;
      if (isActive(job)) dispatch({ type: 'job_restored', job, programId });
      else if (job.status === 'completed' && job.course_id) dispatch({ type: 'job_restored', job, programId });
      else dispatch({ type: 'job_cleared' });
      if (!isActive(job)) localStorage.removeItem(activeJobStorageKey);
    } catch (error: any) {
      // An impersonation/tenant switch can leave a stale id. On a confirmed
      // 404, clear it and immediately discover the active job in this tenant.
      if (error?.response?.status === 404) {
        localStorage.removeItem(activeJobStorageKey);
        clearWorkflowContext();
        try {
          await restoreFromJobList();
        } catch {
          // The job list is optional recovery; keep the page usable.
        }
      }
    }
  }, [restoreFromJobList]);

  const startJob = useCallback((job: AIGenerationJob) => {
    const programId = requestedProgramId || state.programId;
    localStorage.setItem(activeJobStorageKey, job.id);
    persistWorkflowContext(job.id, programId);
    dispatch({ type: 'job_started', job, programId });
  }, [requestedProgramId, state.programId]);

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
    clearWorkflowContext();
    dispatch({ type: 'job_cleared' });
  }, [state.currentJob]);

  const prepareRetry = useCallback(() => {
    localStorage.removeItem(activeJobStorageKey);
    clearWorkflowContext();
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
