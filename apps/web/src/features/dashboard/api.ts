import { getLearningActionCenter } from '@/features/learning-actions/api';
import { api } from '@/lib/api';
import type { MandatoryTrainingSummary } from '@/features/mandatory-training/types';
import type { DashboardCourse, DashboardJob, DashboardSources } from './model';

export const dashboardSections = ['learning', 'courses', 'jobs', 'mandatory'] as const;
export type DashboardSection = typeof dashboardSections[number];

// Each source settles independently; slow summaries must not hold the work queue.
export function loadDashboardSection<Key extends DashboardSection>(key: Key, signal: AbortSignal): Promise<DashboardSources[Key]> {
  const loaders: { [Name in DashboardSection]: () => Promise<DashboardSources[Name]> } = {
    learning: async () => {
      const value = await getLearningActionCenter(undefined, signal);
      return value.summary.training_log ? value : null;
    },
    courses: async () => {
      const response = await api.get<DashboardCourse[]>('/v1/courses?per_page=100', { signal });
      return Array.isArray(response.data) ? response.data : null;
    },
    jobs: async () => {
      const response = await api.get<DashboardJob[]>('/v1/ai/jobs', { signal });
      return Array.isArray(response.data) ? response.data : null;
    },
    mandatory: async () => (await api.get<MandatoryTrainingSummary>('/v1/admin/mandatory-training/summary', { signal })).data,
  };
  return loaders[key]();
}
