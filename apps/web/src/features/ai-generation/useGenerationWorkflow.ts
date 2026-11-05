'use client';

import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
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
const isActive = (job: AIGenerationJob) => job.status === 'pending' || job.status === 'running' || job.status === 'reconciliation_required';
const isRestorable = (job: AIGenerationJob) => isActive(job) || job.status === 'interrupted';

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
  if (job.status === 'failed' || job.status === 'cancelled' || job.status === 'interrupted' || job.status === 'abandoned') return { type: 'job_terminal', job };
  return { type: 'job_active', job };
}

export function useGenerationWorkflow(
  requestedProgramId: string | null = null,
  requestKeyOrJobId?: (() => string) | string | null,
  requestedJobIdArg: string | null = null,
) {
  const getRequestKey = typeof requestKeyOrJobId === 'function' ? requestKeyOrJobId : undefined;
  const requestedJobId = typeof requestKeyOrJobId === 'string' ? requestKeyOrJobId : requestedJobIdArg;
  const [state, dispatch] = useReducer(generationWorkflowReducer, initialGenerationWorkflowState);
  const resumeAttemptRef = useRef<string | null>(null);
  const resumePostingRef = useRef<string | null>(null);
  const resumeRequestKeyRef = useRef<string | undefined>(undefined);
  const mountedRef = useRef(true);
  const getRequestKeyRef = useRef(getRequestKey);
  getRequestKeyRef.current = getRequestKey;
  const [resumeReconciliation, setResumeReconciliation] = useState(false);
  const requestedJobApplied = useRef<string | null>(null);
  const workflowEpoch = useRef(0);
  const requestedJobRef = useRef(requestedJobId);
  requestedJobRef.current = requestedJobId;
  const [requestedJobMissing, setRequestedJobMissing] = useState(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!requestedJobId) setRequestedJobMissing(false);
  }, [requestedJobId]);

  const restoreFromJobList = useCallback(async (isCurrent: () => boolean) => {
    const response = await api.get<AIGenerationJob[]>('/v1/ai/jobs?scope=mine');
    if (!isCurrent()) return;
    const activeJob = selectOldestActiveCourseJob(response.data);
    workflowEpoch.current += 1;
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
    const requestKey = getRequestKeyRef.current?.();
    const isCurrentRequest = () => mountedRef.current
      && (requestKey === undefined || getRequestKeyRef.current?.() === requestKey);
    const epoch = workflowEpoch.current;
    const isCurrent = () => isCurrentRequest() && epoch === workflowEpoch.current && requestedJobRef.current === requestedJobId;
    if (requestedJobId) {
      if (requestedJobApplied.current === requestedJobId) return;
      requestedJobApplied.current = requestedJobId;
      try {
        const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${encodeURIComponent(requestedJobId)}`);
        if (!isCurrent()) return;
        const job = response.data;
        if (job.id !== requestedJobId) throw new Error('requested_job_identity_mismatch');
        const savedContext = readWorkflowContext();
        const programId = savedContext?.job_id === job.id ? savedContext.program_id : null;
        if (isRestorable(job)) {
          localStorage.setItem(activeJobStorageKey, job.id);
          persistWorkflowContext(job.id, programId);
        }
        workflowEpoch.current += 1;
        setRequestedJobMissing(false);
        dispatch({ type: 'job_restored', job, programId });
        return;
      } catch (error: any) {
        if (!isCurrent()) return;
        requestedJobApplied.current = null;
        if (error?.response?.status === 404) setRequestedJobMissing(true);
        // Fall through to the normal recovery path for a transient failure or a
        // job that disappeared after the dashboard was loaded.
      }
    }

    const savedContext = readWorkflowContext();
    const savedJobId = localStorage.getItem(activeJobStorageKey) || savedContext?.job_id;
    if (!savedJobId) {
      try {
        await restoreFromJobList(isCurrent);
      } catch {
        // A missing list is non-blocking; the page remains usable for a new job.
      }
      return;
    }

    try {
      const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${savedJobId}`);
      if (!isCurrent()) return;
      const job = response.data;
      if (!isCurrent()) return;
      if (job.status === 'interrupted' || job.status === 'reconciliation_required') {
        try {
          const listed = await api.get<AIGenerationJob[]>('/v1/ai/jobs?scope=mine');
          if (!isCurrent()) return;
          const liveJob = selectOldestActiveCourseJob(listed.data);
          if (liveJob && (liveJob.status === 'pending' || liveJob.status === 'running')) {
            const listedContext = readWorkflowContext();
            const programId = listedContext?.job_id === liveJob.id ? listedContext.program_id : null;
            localStorage.setItem(activeJobStorageKey, liveJob.id);
            persistWorkflowContext(liveJob.id, programId);
            workflowEpoch.current += 1;
            dispatch({ type: 'job_restored', job: liveJob, programId });
            return;
          }
        } catch {
          // The exact interrupted job remains the safe fallback when discovery is unavailable.
        }
      }
      if (!isCurrent()) return;
      const programId = savedContext?.job_id === job.id ? savedContext.program_id : null;
      if (isRestorable(job)) {
        workflowEpoch.current += 1;
        dispatch({ type: 'job_restored', job, programId });
      }
      else {
        localStorage.removeItem(activeJobStorageKey);
        clearWorkflowContext();
        dispatch({ type: 'job_cleared' });
      }
    } catch (error: any) {
      if (!isCurrent()) return;
      // An impersonation/tenant switch can leave a stale id. On a confirmed
      // 404, clear it and immediately discover the active job in this tenant.
      if (error?.response?.status === 404) {
        if (!isCurrent()) return;
        localStorage.removeItem(activeJobStorageKey);
        clearWorkflowContext();
        try {
          await restoreFromJobList(isCurrent);
        } catch {
          // The job list is optional recovery; keep the page usable.
        }
      }
    }
  }, [requestedJobId, restoreFromJobList]);

  const startJob = useCallback((job: AIGenerationJob, options?: { programId: string | null }) => {
    workflowEpoch.current += 1;
    const programId = options && Object.prototype.hasOwnProperty.call(options, 'programId')
      ? options.programId
      : requestedProgramId || state.programId;
    localStorage.setItem(activeJobStorageKey, job.id);
    persistWorkflowContext(job.id, programId);
    dispatch({ type: 'job_started', job, programId });
  }, [requestedProgramId, state.programId]);

  const refreshJob = useCallback(async () => {
    if (!state.currentJob) return;
    const epoch = workflowEpoch.current;
    const requestKey = getRequestKeyRef.current?.();
    const selectedJobId = requestedJobRef.current;
    const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${state.currentJob.id}`);
    if (!mountedRef.current || epoch !== workflowEpoch.current || selectedJobId !== requestedJobRef.current
        || (requestKey !== undefined && getRequestKeyRef.current?.() !== requestKey)) return;
    const job = response.data;
    if (job.id !== state.currentJob.id) throw new Error('refresh_job_identity_mismatch');
    dispatch(actionForPolledJob(job));
    if (!isRestorable(job)) {
      localStorage.removeItem(activeJobStorageKey);
      clearWorkflowContext();
    }
  }, [state.currentJob]);

  const cancelJob = useCallback(async () => {
    if (!state.currentJob) return;
    const epoch = workflowEpoch.current;
    const requestKey = getRequestKeyRef.current?.();
    const selectedJobId = requestedJobRef.current;
    await api.post(`/v1/ai/jobs/${state.currentJob.id}/cancel`);
    if (!mountedRef.current || epoch !== workflowEpoch.current || selectedJobId !== requestedJobRef.current
        || (requestKey !== undefined && getRequestKeyRef.current?.() !== requestKey)) return;
    workflowEpoch.current += 1;
    localStorage.removeItem(activeJobStorageKey);
    clearWorkflowContext();
    dispatch({ type: 'job_cleared' });
  }, [state.currentJob]);

  const resumeJob = useCallback(async () => {
    if (!state.currentJob || state.currentJob.status !== 'interrupted') return;
    const jobId = state.currentJob.id;
    const requestKey = getRequestKey?.();
    const epoch = workflowEpoch.current;
    const selectedJobId = requestedJobRef.current;
    const isCurrentRequest = () => (requestKey === undefined || getRequestKey?.() === requestKey)
      && epoch === workflowEpoch.current && selectedJobId === requestedJobRef.current;
    if (resumeRequestKeyRef.current !== undefined && resumeRequestKeyRef.current !== requestKey) {
      resumeAttemptRef.current = null;
      resumePostingRef.current = null;
      resumeRequestKeyRef.current = undefined;
    }
    if (resumePostingRef.current === jobId) return;
    if (resumeAttemptRef.current === jobId) {
      const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${jobId}`);
      if (response.data.id !== jobId) throw new Error('resume_job_identity_mismatch');
      if (!mountedRef.current || !isCurrentRequest()) return response.data;
      dispatch(actionForPolledJob(response.data));
      if (response.data.status !== 'interrupted') {
        resumeAttemptRef.current = null;
        resumePostingRef.current = null;
        resumeRequestKeyRef.current = undefined;
        setResumeReconciliation(false);
      }
      return response.data;
    }
    resumeAttemptRef.current = jobId;
    resumePostingRef.current = jobId;
    resumeRequestKeyRef.current = requestKey;
    try {
      const response = await api.post<AIGenerationJob>(`/v1/ai/jobs/${jobId}/resume`);
      if (response.data.id !== jobId) throw new Error('resume_job_identity_mismatch');
      if (!mountedRef.current || !isCurrentRequest()) return response.data;
      localStorage.setItem(activeJobStorageKey, response.data.id);
      persistWorkflowContext(response.data.id, state.programId);
      dispatch({ type: 'job_started', job: response.data, programId: state.programId });
      setResumeReconciliation(false);
      resumeAttemptRef.current = null;
      resumePostingRef.current = null;
      resumeRequestKeyRef.current = undefined;
      return response.data;
    } catch (error: any) {
      if (!mountedRef.current || !isCurrentRequest()) return;
      const status = error?.response?.status;
      const code = error?.response?.data?.detail?.code ?? error?.response?.data?.details?.code;
      if (status === undefined || status === 503 || (status >= 500 && status <= 599) || code === 'ai_job_dispatch_outcome_unknown') {
        setResumeReconciliation(true);
        // The POST attempt has settled. Keep the attempt fence, but allow a
        // subsequent explicit status check to perform the read-only GET.
        resumePostingRef.current = null;
        const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${jobId}`);
        if (response.data.id !== jobId) throw new Error('resume_job_identity_mismatch');
        if (!mountedRef.current || !isCurrentRequest()) return response.data;
        dispatch(actionForPolledJob(response.data));
        if (response.data.status !== 'interrupted') {
          resumeAttemptRef.current = null;
          resumePostingRef.current = null;
          resumeRequestKeyRef.current = undefined;
          setResumeReconciliation(false);
        }
        return response.data;
      }
      resumeAttemptRef.current = null;
      resumePostingRef.current = null;
      resumeRequestKeyRef.current = undefined;
      throw error;
    }
  }, [getRequestKey, state.currentJob, state.programId]);

  const prepareRetry = useCallback(() => {
    workflowEpoch.current += 1;
    localStorage.removeItem(activeJobStorageKey);
    clearWorkflowContext();
    dispatch({ type: 'job_cleared' });
  }, []);

  const resetWorkflow = useCallback(() => {
    workflowEpoch.current += 1;
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
    requestedJobMissing,
    restoreActiveJob,
    startJob,
    refreshJob,
    cancelJob,
    resumeJob,
    resumeReconciliation,
    prepareRetry,
    resetWorkflow,
  };
}
