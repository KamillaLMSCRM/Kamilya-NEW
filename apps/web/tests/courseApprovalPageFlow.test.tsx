import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listCoursesMock = vi.hoisted(() => vi.fn());
const listRequestsMock = vi.hoisted(() => vi.fn());
const authSelectorMock = vi.hoisted(() => vi.fn());
const searchParams = vi.hoisted(() => ({ get: () => null }));
vi.mock('@/lib/courseApproval', () => ({ listApprovalCourses: listCoursesMock, listApprovalRequests: listRequestsMock }));
vi.mock('@/store/authStore', () => ({ useAuthStore: authSelectorMock }));
vi.mock('next/navigation', () => ({ useSearchParams: () => searchParams }));
vi.mock('@/components/course-approval/ApprovalPolicyCard', () => ({ ApprovalPolicyCard: ({ courseId }: { courseId: string }) => <div data-testid="policy-card">policy:{courseId}</div> }));
vi.mock('@/components/course-approval/ApprovalStatusPanel', () => ({ ApprovalStatusPanel: () => <div data-testid="status-panel" /> }));
vi.mock('@/components/course-approval/ApprovalRequestModal', () => ({ ApprovalRequestModal: ({ open, courseId }: { open: boolean; courseId: string }) => open ? <div role="dialog">request-modal:{courseId}</div> : null }));

import CourseApprovalsPage from '@/app/admin/course-approvals/page';

describe('course approval course-switch and create flow', () => {
  beforeEach(() => {
    authSelectorMock.mockImplementation((selector: (state: { user: { role: string } }) => unknown) => selector({ user: { role: 'methodologist' } }));
    listCoursesMock.mockResolvedValue([{ id: 'course-a', title: 'Course A', requires_approval: false }, { id: 'course-b', title: 'Course B', requires_approval: true }]);
    listRequestsMock.mockResolvedValue([]);
  });

  it('resets the selected-course controls and opens a request for the switched course', async () => {
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('course-a'));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'course-b' } });
    expect(screen.getAllByTestId('policy-card')).toHaveLength(1);
    expect(screen.getByTestId('policy-card')).toHaveTextContent('policy:course-b');
    fireEvent.click(screen.getByRole('button', { name: 'Создать снимок и запрос' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('request-modal:course-b');
  });
});
