import { getLearningActionCenter } from '@/features/learning-actions/api';
import { api } from '@/lib/api';
import type { MandatoryTrainingSummary } from '@/features/mandatory-training/types';
import { buildMethodologistDashboard, type DashboardCourse, type DashboardJob, type MethodologistDashboardModel } from './model';

export async function loadMethodologistDashboard(signal: AbortSignal): Promise<MethodologistDashboardModel> {
  const [learning, courses, jobs, mandatory] = await Promise.allSettled([
    getLearningActionCenter(undefined, signal),
    api.get<DashboardCourse[]>('/v1/courses', { signal }),
    api.get<DashboardJob[]>('/v1/ai/jobs', { signal }),
    api.get<MandatoryTrainingSummary>('/v1/admin/mandatory-training/summary', { signal }),
  ]);

  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');

  return buildMethodologistDashboard({
    learning: learning.status === 'fulfilled' ? learning.value : null,
    courses: courses.status === 'fulfilled' && Array.isArray(courses.value.data) ? courses.value.data : null,
    jobs: jobs.status === 'fulfilled' && Array.isArray(jobs.value.data) ? jobs.value.data : null,
    mandatory: mandatory.status === 'fulfilled' ? mandatory.value.data : null,
  });
}
