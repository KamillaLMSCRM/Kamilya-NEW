export interface AIGenerationJob {
  id: string;
  status: string;
  job_type?: string;
  course_id: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  progress: number;
  progress_current?: number | null;
  progress_total?: number | null;
  estimated_remaining_seconds?: number | null;
  progress_attempt?: number | null;
  progress_provider?: string | null;
  stage: string;
  message: string;
  queue_position: number | null;
  estimated_wait_seconds: number | null;
  tenant_active_jobs: number | null;
  tenant_active_limit: number | null;
  abandon_available?: boolean;
  retained_response_replay_available?: boolean;
}

export interface AIGenerationWorkflowContext {
  job_id: string;
  program_id: string | null;
}

export function selectOldestActiveCourseJob(
  jobs: AIGenerationJob[],
): AIGenerationJob | null {
  const candidates = jobs
    .filter((job) => (
      (
        job.job_type === 'course_generation'
        || (job.job_type === undefined && job.course_id !== null)
      )
      && (job.status === 'pending' || job.status === 'running' || job.status === 'interrupted' || job.status === 'reconciliation_required')
    ))
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at));
  const live = candidates.filter((job) => (
    job.status === 'pending' || job.status === 'running'
  ));
  return (live[0] ?? candidates.find((job) => job.status === 'reconciliation_required' || job.status === 'interrupted')) ?? null;
}

export function selectLatestTerminalCourseJob(
  jobs: AIGenerationJob[],
): AIGenerationJob | null {
  const terminalJobs = jobs
    .filter((job) => (
      job.job_type === 'course_generation'
      && (job.status === 'failed' || job.status === 'cancelled' || job.status === 'interrupted')
    ))
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
  return terminalJobs[0] ?? null;
}
