export interface TenantUsageCounters {
  ai_course_generations_used: number;
  ai_course_generations_limit: number | null;
  jd_course_generations_used: number;
  jd_course_generations_limit: number | null;
  active_students_count_snapshot: number;
  active_students_limit: number | null;
  system_users_count_snapshot: number;
  system_users_limit: number | null;
  updated_at: string | null;
}

export function formatUsageCounter(
  used: number | null | undefined,
  limit: number | null | undefined,
  unlimitedLabel: string,
): string {
  return `${used ?? 0} / ${limit == null ? unlimitedLabel : limit}`;
}
