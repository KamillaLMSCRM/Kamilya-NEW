import { selectOldestActiveCourseJob } from '@/lib/aiGenerationJobs';
import { describe, expect, it } from 'vitest';

const job = (
  id: string,
  createdAt: string,
  courseId: string | null,
  stage: string,
) => ({
  id,
  status: 'running',
  course_id: courseId,
  created_at: createdAt,
  updated_at: createdAt,
  progress: 30,
  stage,
  message: '',
  queue_position: null,
  estimated_wait_seconds: null,
  tenant_active_jobs: null,
  tenant_active_limit: null,
});

describe('AI generation job recovery', () => {
  it('ignores document indexing jobs without a generated course', () => {
    const selected = selectOldestActiveCourseJob([
      job('document-index', '2026-08-06T08:00:00Z', null, 'index'),
      job('course-generation', '2026-08-06T08:01:00Z', 'course-1', 'content_generation'),
    ]);

    expect(selected?.id).toBe('course-generation');
  });
});
