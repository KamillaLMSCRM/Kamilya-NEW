import type { LearningActionCenterPayload, TrainingAttentionItem } from '@/features/learning-actions/types';

export interface DashboardCourse {
  id: string;
  title: string;
  status: string;
}

export interface DashboardJob {
  id: string;
  status: string;
  job_type?: string;
  stage?: string;
  course_title?: string;
  created_at: string;
}

export interface DashboardSources {
  learning: LearningActionCenterPayload | null;
  courses: DashboardCourse[] | null;
  jobs: DashboardJob[] | null;
}

export interface MethodologistDashboardModel {
  learningAvailable: boolean;
  training: null | {
    total: number;
    notStarted: number;
    inProgress: number;
    completed: number;
    overdue: number;
    failed: number;
    exhausted: number;
    completionPercent: number;
  };
  attention: null | {
    trainingIssues: number;
    weakQuestions: number;
    openActions: number;
    overdueActions: number;
    items: TrainingAttentionItem[];
    truncated: boolean;
  };
  content: {
    coursesAvailable: boolean;
    totalCourses: number | null;
    publishedCourses: number | null;
    draftCourses: number | null;
    jobsAvailable: boolean;
    activeJobs: number | null;
    attentionJobs: number | null;
    jobs: DashboardJob[];
  };
}

const ACTIVE_JOB_STATUSES = new Set(['pending', 'running']);
const HIDDEN_JOB_STATUSES = new Set(['completed', 'cancelled']);

export function buildMethodologistDashboard(sources: DashboardSources): MethodologistDashboardModel {
  const log = sources.learning?.summary.training_log ?? null;
  const visibleJobs = (sources.jobs ?? [])
    .filter((job) => job.job_type === 'course_generation' && !HIDDEN_JOB_STATUSES.has(job.status))
    .slice(0, 5);

  return {
    learningAvailable: Boolean(log && sources.learning),
    training: log ? {
      total: log.total,
      notStarted: log.assigned,
      inProgress: log.in_progress,
      completed: log.completed,
      overdue: log.overdue,
      failed: log.failed_current,
      exhausted: log.exhausted_attempts,
      completionPercent: log.total > 0 ? Math.round((log.completed / log.total) * 100) : 0,
    } : null,
    attention: sources.learning && log ? {
      trainingIssues: sources.learning.summary.training_issue_count,
      weakQuestions: sources.learning.summary.weak_question_count,
      openActions: sources.learning.summary.open_action_count,
      overdueActions: sources.learning.summary.overdue_action_count,
      items: sources.learning.training_items.slice(0, 3),
      truncated: sources.learning.summary.training_items_truncated,
    } : null,
    content: {
      coursesAvailable: sources.courses !== null,
      totalCourses: sources.courses?.length ?? null,
      publishedCourses: sources.courses?.filter((course) => course.status === 'published').length ?? null,
      draftCourses: sources.courses?.filter((course) => course.status !== 'published').length ?? null,
      jobsAvailable: sources.jobs !== null,
      activeJobs: sources.jobs === null ? null : visibleJobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status)).length,
      attentionJobs: sources.jobs === null ? null : visibleJobs.filter((job) => !ACTIVE_JOB_STATUSES.has(job.status)).length,
      jobs: visibleJobs,
    },
  };
}
