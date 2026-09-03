import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listCoursesMock = vi.hoisted(() => vi.fn());
const listRequestsMock = vi.hoisted(() => vi.fn());
const cancelMock = vi.hoisted(() => vi.fn());
const resendMock = vi.hoisted(() => vi.fn());
const revokeMock = vi.hoisted(() => vi.fn());
const authSelectorMock = vi.hoisted(() => vi.fn());
const searchParams = vi.hoisted(() => ({ get: () => null }));
vi.mock('@/lib/courseApproval', () => ({ listApprovalCourses: listCoursesMock, listApprovalRequests: listRequestsMock, cancelApprovalRequest: cancelMock, resendApprovalDelivery: resendMock, revokeApprovalAccess: revokeMock }));
vi.mock('@/store/authStore', () => ({ useAuthStore: authSelectorMock }));
vi.mock('next/navigation', () => ({ useSearchParams: () => searchParams }));
vi.mock('@/components/course-approval/ApprovalPolicyCard', () => ({ ApprovalPolicyCard: ({ courseId }: { courseId: string }) => <div data-testid="policy-card">policy:{courseId}</div> }));
vi.mock('@/components/course-approval/ApprovalRequestModal', () => ({ ApprovalRequestModal: ({ open, courseId }: { open: boolean; courseId: string }) => open ? <div role="dialog">request-modal:{courseId}</div> : null }));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import CourseApprovalsPage from '@/app/admin/course-approvals/page';

describe('course approval course-switch and create flow', () => {
  beforeEach(() => {
    authSelectorMock.mockImplementation((selector: (state: { user: { role: string } }) => unknown) => selector({ user: { role: 'methodologist' } }));
    listCoursesMock.mockResolvedValue([{ id: 'course-a', title: 'Course A', requires_approval: false }, { id: 'course-b', title: 'Course B', requires_approval: true }]);
    listRequestsMock.mockResolvedValue([{ request_id: 'request-1', revision_id: 'revision-1', outcome: 'pending', delivery_mode: 'personal_link', reviewer_ids: ['reviewer-1'] }]);
    cancelMock.mockReset().mockResolvedValue(undefined);
    resendMock.mockReset().mockResolvedValue({ request_id: 'request-1', rotated: true, retried: 0, access_credentials: [{ reviewer_id: 'reviewer-1', access_url: 'https://example.test/new', temporary_pin: '654321', expires_at: '2027-01-01T00:00:00Z' }] });
    revokeMock.mockReset().mockResolvedValue(undefined);
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

  it('opens the real cancellation confirmation before making an API call', async () => {
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отменить запрос' })).toBeInTheDocument());
    const cancelButton = screen.getByRole('button', { name: 'Отменить запрос' });
    expect(cancelButton).toHaveAttribute('type', 'button');
    fireEvent.click(cancelButton);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(cancelMock).not.toHaveBeenCalled();
  });

  it('opens the real rotation confirmation before making an API call', async () => {
    render(<CourseApprovalsPage />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сменить доступ' })).toBeInTheDocument());
    const rotateButton = screen.getByRole('button', { name: 'Сменить доступ' });
    expect(rotateButton).toHaveAttribute('type', 'button');
    fireEvent.click(rotateButton);
    expect(screen.getByRole('dialog')).toHaveTextContent(/новый секрет будет показан один раз/i);
    expect(resendMock).not.toHaveBeenCalled();
  });
});
