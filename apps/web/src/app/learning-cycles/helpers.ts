export type OccurrenceState = 'assigned' | 'overdue' | 'completed' | 'completed_late' | 'skipped';

export type OccurrenceLike = {
  status: string;
  due_at: string;
  completed_at: string | null;
};

export function deriveOccurrenceState(
  occurrence: OccurrenceLike,
  now: Date = new Date(),
): OccurrenceState {
  if (occurrence.completed_at) {
    return new Date(occurrence.completed_at) > new Date(occurrence.due_at)
      ? 'completed_late'
      : 'completed';
  }
  if (occurrence.status === 'assigned' && new Date(occurrence.due_at) < now) return 'overdue';
  if (occurrence.status === 'overdue') return 'overdue';
  if (occurrence.status === 'skipped') return 'skipped';
  return 'assigned';
}

export function correctiveAssignmentUrl(courseId: string | null, userId: string): string | null {
  if (!courseId || !userId) return null;
  const query = new URLSearchParams({ course_id: courseId, user_id: userId });
  return `/assignments?${query.toString()}`;
}

export type BulkResult<T> = { item: T; ok: true } | { item: T; ok: false; error: unknown };

export async function collectPages<T>(
  loadPage: (page: number, pageSize: number) => Promise<readonly T[]>,
  pageSize: number,
  maxPages = 100,
): Promise<T[]> {
  const result: T[] = [];
  for (let page = 1; page <= maxPages; page += 1) {
    const items = await loadPage(page, pageSize);
    result.push(...items);
    if (items.length < pageSize) return result;
  }
  throw new Error('pagination_limit_exceeded');
}

export async function runBounded<T>(
  items: readonly T[],
  action: (item: T) => Promise<unknown>,
  concurrency = 3,
): Promise<BulkResult<T>[]> {
  const results: BulkResult<T>[] = new Array(items.length);
  let cursor = 0;
  const worker = async () => {
    while (true) {
      const index = cursor++;
      if (index >= items.length) return;
      const item = items[index];
      try {
        await action(item);
        results[index] = { item, ok: true };
      } catch (error) {
        results[index] = { item, ok: false, error };
      }
    }
  };
  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, items.length || 1)) }, worker));
  return results;
}

export function isResendEligible(occurrence: {
  target_type: string;
  course_id: string | null;
  enrollment_id: string | null;
  completed_at: string | null;
  status: string;
}): boolean {
  return occurrence.target_type === 'course'
    && Boolean(occurrence.course_id && occurrence.enrollment_id)
    && occurrence.completed_at === null
    && (occurrence.status === 'assigned' || occurrence.status === 'overdue');
}
