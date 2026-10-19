'use client';

import { useCallback, useEffect, useReducer, useRef } from 'react';
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
const terminalResetBoundaryStorageKey = 'ai_generation_terminal_reset_boundary';
const isActive = (job: AIGenerationJob) => job.status === 'pending' || job.status === 'running';
const isRestorable = (job: AIGenerationJob) => isActive(job) || job.status === 'interrupted';
const isTerminal = (job: AIGenerationJob) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status);

interface TerminalResetBoundary {
  reset_at: number;
  job_id: string;
}

function readTerminalResetBoundary(): TerminalResetBoundary | null {
  const raw = localStorage.getItem(terminalResetBoundaryStorageKey);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<TerminalResetBoundary>;
    if (!Number.isFinite(value.reset_at) || typeof value.job_id !== 'string' || !value.job_id) return null;
    return { reset_at: value.reset_at!, job_id: value.job_id };
  } catch {
    return null;
  }
}

function recordTerminalResetBoundary(job: AIGenerationJob | null) {
  if (!job || !isTerminal(job)) return;
  const existing = readTerminalResetBoundary();
  const jobTimestamp = Math.max(
    Number.isFinite(Date.parse(job.created_at)) ? Date.parse(job.created_at) : 0,
    Number.isFinite(Date.parse(job.updated_at)) ? Date.parse(job.updated_at) : 0,
  );
  const boundary = {
    reset_at: Math.max(existing?.reset_at ?? 0, Date.now(), jobTimestamp),
    job_id: job.id,
  };
  localStorage.setItem(terminalResetBoundaryStorageKey, JSON.stringify(boundary));
}

function wasInterruptedBeforeReset(job: AIGenerationJob): boolean {
  if (job.status !== 'interrupted') return false;
  const boundary = readTerminalResetBoundary();
  if (!boundary) return false;
  if (job.id === boundary.job_id) return true;
  const createdAt = Date.parse(job.created_at);
  return !Number.isFinite(createdAt) || createdAt <= boundary.reset_at;
}

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
  if (job.status === 'failed' || job.status === 'cancelled' || job.status === 'interrupted') return { type: 'job_terminal', job };
  return { type: 'job_active', job };
}

export function useGenerationWorkflow(requestedProgramId: string | null = null) {
  const [state, dispatch] = useReducer(generationWorkflowReducer, initialGenerationWorkflowState);
  const restoreEpochRef = useRef(0);

  const restoreFromJobList = useCallback(async () => {
    const restoreEpoch = restoreEpochRef.current;
    const response = await api.get<AIGenerationJob[]>('/v1/ai/jobs?scope=mine');
    if (restoreEpoch !== restoreEpochRef.current) return;
    const activeJob = selectOldestActiveCourseJob(
      response.data.filter((job) => !wasInterruptedBeforeReset(job)),
    );
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
    const restoreEpoch = restoreEpochRef.current;
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
      if (restoreEpoch !== restoreEpochRef.current) return;
      const job = response.data;
      const programId = savedContext?.job_id === job.id ? savedContext.program_id : null;
      if (isRestorable(job) && !wasInterruptedBeforeReset(job)) dispatch({ type: 'job_restored', job, programId });
      else {
        localStorage.removeItem(activeJobStorageKey);
        clearWorkflowContext();
        dispatch({ type: 'job_cleared' });
      }
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
    restoreEpochRef.current += 1;
    const programId = requestedProgramId || state.programId;
    localStorage.setItem(activeJobStorageKey, job.id);
    persistWorkflowContext(job.id, programId);
    dispatch({ type: 'job_started', job, programId });
  }, [requestedProgramId, state.programId]);

  const refreshJob = useCallback(async () => {
    if (!state.currentJob) return;
    const refreshEpoch = restoreEpochRef.current;
    const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${state.currentJob.id}`);
    if (refreshEpoch !== restoreEpochRef.current) return;
    const job = response.data;
    dispatch(actionForPolledJob(job));
    if (!isRestorable(job)) {
      localStorage.removeItem(activeJobStorageKey);
      clearWorkflowContext();
    }
  }, [state.currentJob]);

  const cancelJob = useCallback(async () => {
    if (!state.currentJob) return;
    await api.post(`/v1/ai/jobs/${state.currentJob.id}/cancel`);
    restoreEpochRef.current += 1;
    localStorage.removeItem(activeJobStorageKey);
    clearWorkflowContext();
    dispatch({ type: 'job_cleared' });
  }, [state.currentJob]);

  const resumeJob = useCallback(async () => {
    if (!state.currentJob || state.currentJob.status !== 'interrupted') return;
    const response = await api.post<AIGenerationJob>(`/v1/ai/jobs/${state.currentJob.id}/resume`);
    localStorage.setItem(activeJobStorageKey, response.data.id);
    persistWorkflowContext(response.data.id, state.programId);
    dispatch({ type: 'job_started', job: response.data, programId: state.programId });
  }, [state.currentJob, state.programId]);

  const prepareRetry = useCallback(() => {
    restoreEpochRef.current += 1;
    recordTerminalResetBoundary(state.currentJob);
    localStorage.removeItem(activeJobStorageKey);
    clearWorkflowContext();
    dispatch({ type: 'job_cleared' });
  }, [state.currentJob]);

  const resetWorkflow = useCallback(() => {
    restoreEpochRef.current += 1;
    recordTerminalResetBoundary(state.currentJob);
    localStorage.removeItem(activeJobStorageKey);
    clearWorkflowContext();
    dispatch({ type: 'job_cleared' });
  }, [state.currentJob]);

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
    resumeJob,
    prepareRetry,
    resetWorkflow,
  };
}
