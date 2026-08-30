import {
  selectLatestTerminalCourseJob,
  selectOldestActiveCourseJob,
} from '@/lib/aiGenerationJobs';
import { describe, expect, it } from 'vitest';

const job = (
  id: string,
  createdAt: string,
  courseId: string | null,
  stage: string,
  jobType?: string,
) => ({
  id,
  status: 'running',
  job_type: jobType,
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
  it('restores a course-generation job before the course record exists', () => {
    const selected = selectOldestActiveCourseJob([
      job('document-index', '2026-08-06T08:00:00Z', null, 'index', 'document_reindex'),
      job('course-generation', '2026-08-06T08:01:00Z', null, 'content_generation', 'course_generation'),
    ]);

    expect(selected?.id).toBe('course-generation');
  });

  it('selects the oldest active course generation and ignores regeneration jobs', () => {
    const selected = selectOldestActiveCourseJob([
      job('newer', '2026-08-06T08:02:00Z', null, 'architect', 'course_generation'),
      job('lesson', '2026-08-06T08:00:00Z', 'course-1', 'regenerate', 'regenerate_lesson'),
      job('older', '2026-08-06T08:01:00Z', null, 'architect', 'course_generation'),
    ]);

    expect(selected?.id).toBe('older');
  });

  it('keeps the result-based fallback for a staggered legacy API response', () => {
    const selected = selectOldestActiveCourseJob([
      job('legacy', '2026-08-06T08:00:00Z', 'course-1', 'content_generation'),
    ]);

    expect(selected?.id).toBe('legacy');
  });

  it('selects only the latest terminal course-generation job', () => {
    const olderFailed = { ...job('older', '2026-08-06T08:00:00Z', null, 'failed', 'course_generation'), status: 'failed' };
    const latestFailed = { ...job('latest', '2026-08-06T08:01:00Z', null, 'failed', 'course_generation'), status: 'failed' };
    const indexingFailed = { ...job('index', '2026-08-06T08:02:00Z', null, 'failed', 'document_reindex'), status: 'failed' };

    expect(selectLatestTerminalCourseJob([olderFailed, latestFailed, indexingFailed])?.id).toBe('latest');
  });
});
