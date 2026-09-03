import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { get: getMock } }));

import { listApprovalCourses } from '@/lib/courseApproval';

describe('course approval course catalog pagination', () => {
  beforeEach(() => getMock.mockReset());

  it('uses the backend maximum page size and consumes the bounded list contract', async () => {
    getMock.mockResolvedValueOnce({ data: [{ id: 'course-1', title: 'One' }] });
    await expect(listApprovalCourses()).resolves.toEqual([{ id: 'course-1', title: 'One' }]);
    expect(getMock).toHaveBeenCalledWith('/v1/courses?page=1&per_page=100');
    expect(getMock.mock.calls.every(([url]) => !String(url).includes('per_page=101'))).toBe(true);
  });

  it('continues through a full page and supports the legacy items envelope', async () => {
    getMock.mockResolvedValueOnce({ data: Array.from({ length: 100 }, (_, index) => ({ id: `course-${index}`, title: `Course ${index}` })) });
    getMock.mockResolvedValueOnce({ data: { items: [{ id: 'course-100', title: 'Course 100' }] } });
    const rows = await listApprovalCourses();
    expect(rows).toHaveLength(101);
    expect(getMock).toHaveBeenNthCalledWith(2, '/v1/courses?page=2&per_page=100');
  });
});
