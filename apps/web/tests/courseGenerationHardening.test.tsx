import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { GenerationProgressPanel } from '@/features/ai-generation/GenerationProgressPanel';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';

const stages = [
  { key: 'content_generation', label: 'Content generation', icon: () => null, color: 'text-primary' },
];

const labels = {
  queued: 'Queued', running: 'Running', completed: 'Completed', failed: 'Failed',
  cancelled: 'Cancelled', interrupted: 'Interrupted', stalled: 'Stalled',
};

const job: AIGenerationJob = {
  id: 'job-1', status: 'completed', job_type: 'course_generation', course_id: 'course-1',
  created_at: '2026-09-14T08:00:00Z', updated_at: '2026-09-14T08:02:00Z',
  progress: 100, progress_current: 6, progress_total: 6,
  estimated_remaining_seconds: 0, stage: 'completed', message: 'Saved',
  queue_position: null, estimated_wait_seconds: null,
  tenant_active_jobs: null, tenant_active_limit: null,
};

describe('course generation progress honesty', () => {
  it('keeps exact completed stage units visible and does not invent an ETA', () => {
    render(
      <GenerationProgressPanel
        job={job}
        stages={stages}
        title="Generation progress"
        labels={labels}
        retryLabel="Retry"
        checkAgainLabel="Check again"
        cancelLabel="Cancel"
        cancelQueuedLabel="Cancel queued"
        queueTitle="Queue"
        activeJobs=""
        queuePosition=""
        estimatedWait=""
        queueEstimateHint=""
        completedUnitsLabel="Saved lessons"
        onRetry={() => undefined}
        onCancel={() => undefined}
      />,
    );

    expect(screen.getByText('Saved lessons: 6 / 6')).toBeInTheDocument();
    expect(screen.queryByText(/≈/)).not.toBeInTheDocument();
    expect(screen.queryByText(/estimate|remaining|мин|minute/i)).not.toBeInTheDocument();
  });
});
