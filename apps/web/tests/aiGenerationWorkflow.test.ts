import { describe, expect, it } from 'vitest';
import {
  generationWorkflowReducer,
  initialGenerationWorkflowState,
} from '@/features/ai-generation/generationWorkflow';

const job = (status: string, courseId: string | null = 'course-1') => ({
  id: 'job-1', status, course_id: courseId, created_at: '2026-08-07T08:00:00Z',
  updated_at: '2026-08-07T08:00:00Z', progress: 30, stage: 'content_generation', message: '',
  queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: null, tenant_active_limit: null,
});

describe('AI generation workflow transitions', () => {
  it('moves a newly submitted or restored active job to generation', () => {
    const started = generationWorkflowReducer(initialGenerationWorkflowState, { type: 'job_started', job: job('pending') });
    const restored = generationWorkflowReducer(initialGenerationWorkflowState, { type: 'job_active', job: job('running') });

    expect(started).toMatchObject({ step: 'generate', currentJob: { status: 'pending' } });
    expect(restored).toMatchObject({ step: 'generate', currentJob: { status: 'running' } });
  });

  it('moves a completed course to review while retaining the job for the preview', () => {
    const state = generationWorkflowReducer(initialGenerationWorkflowState, { type: 'job_completed', job: job('completed') });

    expect(state).toMatchObject({ step: 'review', currentJob: { course_id: 'course-1' } });
  });

  it('keeps failed jobs visible for retry and clears them before cancel or retry', () => {
    const terminal = generationWorkflowReducer(initialGenerationWorkflowState, { type: 'job_terminal', job: job('failed') });
    const cleared = generationWorkflowReducer(terminal, { type: 'job_cleared' });

    expect(terminal).toMatchObject({ step: 'generate', currentJob: { status: 'failed' } });
    expect(cleared).toEqual(initialGenerationWorkflowState);
  });
});
