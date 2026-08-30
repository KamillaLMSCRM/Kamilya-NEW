export interface AIGenerationJob {
  id: string;
  status: string;
  job_type?: string;
  course_id: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  progress: number;
  stage: string;
  message: string;
  queue_position: number | null;
  estimated_wait_seconds: number | null;
  tenant_active_jobs: number | null;
  tenant_active_limit: number | null;
}

export function selectOldestActiveCourseJob(
  jobs: AIGenerationJob[],
): AIGenerationJob | null {
  const activeJobs = jobs
    .filter((job) => (
      (
        job.job_type === 'course_generation'
        || (job.job_type === undefined && job.course_id !== null)
      )
      && (job.status === 'pending' || job.status === 'running')
    ))
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at));
  return activeJobs[0] ?? null;
}

export function selectLatestTerminalCourseJob(
  jobs: AIGenerationJob[],
): AIGenerationJob | null {
  const terminalJobs = jobs
    .filter((job) => (
      job.job_type === 'course_generation'
      && (job.status === 'failed' || job.status === 'cancelled')
    ))
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
  return terminalJobs[0] ?? null;
}
