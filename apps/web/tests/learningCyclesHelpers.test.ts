import { describe, expect, it, vi } from 'vitest';
import { collectPages, correctiveAssignmentUrl, deriveOccurrenceState, isResendEligible, runBounded } from '@/app/learning-cycles/helpers';

describe('learning cycle operations helpers', () => {
  it('collects every backend page and stops after the short final page', async () => {
    const loadPage = vi.fn(async (page: number, pageSize: number) => (
      page === 1
        ? Array.from({ length: pageSize }, (_, index) => `item-${index}`)
        : ['last-item']
    ));
    const rows = await collectPages(loadPage, 2);
    expect(rows).toEqual(['item-0', 'item-1', 'last-item']);
    expect(loadPage).toHaveBeenNthCalledWith(1, 1, 2);
    expect(loadPage).toHaveBeenNthCalledWith(2, 2, 2);
  });

  it('fails closed when an endpoint never advances pagination', async () => {
    await expect(collectPages(async () => ['same'], 1, 2)).rejects.toThrow('pagination_limit_exceeded');
  });

  it('derives overdue and completed-late from due/completion timestamps', () => {
    const now = new Date('2026-09-22T12:00:00Z');
    expect(deriveOccurrenceState({ status: 'assigned', due_at: '2026-09-21T00:00:00Z', completed_at: null }, now)).toBe('overdue');
    expect(deriveOccurrenceState({ status: 'completed', due_at: '2026-09-21T00:00:00Z', completed_at: '2026-09-22T00:00:00Z' }, now)).toBe('completed_late');
    expect(deriveOccurrenceState({ status: 'overdue', due_at: '2026-09-21T00:00:00Z', completed_at: '2026-09-20T12:00:00Z' }, now)).toBe('completed');
  });

  it('builds the exact corrective-assignment URL and rejects incomplete identity', () => {
    expect(correctiveAssignmentUrl('course /1', 'user&2')).toBe('/assignments?course_id=course+%2F1&user_id=user%262');
    expect(correctiveAssignmentUrl(null, 'user')).toBeNull();
  });

  it('only enables resend for unfinished course occurrences with enrollment identity', () => {
    const base = { target_type: 'course', course_id: 'c', enrollment_id: 'e', completed_at: null, status: 'overdue' };
    expect(isResendEligible(base)).toBe(true);
    expect(isResendEligible({ ...base, target_type: 'learning_path' })).toBe(false);
    expect(isResendEligible({ ...base, completed_at: '2026-01-01' })).toBe(false);
    expect(isResendEligible({ ...base, enrollment_id: null })).toBe(false);
  });

  it('bounds parallel work and preserves per-item failures for partial feedback', async () => {
    let active = 0;
    let maximum = 0;
    const action = vi.fn(async (value: number) => {
      active += 1;
      maximum = Math.max(maximum, active);
      await Promise.resolve();
      active -= 1;
      if (value === 2) throw new Error('rejected');
    });
    const result = await runBounded([1, 2, 3, 4], action, 2);
    expect(maximum).toBeLessThanOrEqual(2);
    expect(result.map((entry) => entry.ok)).toEqual([true, false, true, true]);
    expect(result[1]).toMatchObject({ item: 2, ok: false });
  });
});
