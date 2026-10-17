import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
const freezeMock = vi.hoisted(() => vi.fn());
const createMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { get: getMock } }));
vi.mock('@/lib/courseApproval', () => ({ freezeApprovalRevision: freezeMock, createApprovalRequest: createMock }));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: (key: string) => ({
    'courseApproval.reviewers': 'Рецензенты',
    'courseApproval.noReviewers': 'Нет доступных рецензентов.',
    'courseApproval.errorLoad': 'Не удалось открыть согласование.',
    'courseApproval.retry': 'Повторить',
    'courseApproval.methodologist': 'Методист',
    'courseApproval.administrator': 'Администратор',
    'courseApproval.externalGuest': 'Внешний рецензент',
    'courseApproval.guestName': 'Имя',
    'courseApproval.guestEmail': 'Email гостя',
    'courseApproval.removeGuest': 'Удалить гостя',
    'courseApproval.addGuest': 'Добавить гостя',
    'courseApproval.delivery': 'Доставка',
    'courseApproval.email': 'Email',
    'courseApproval.personalLink': 'Ссылка и PIN',
    'courseApproval.deadline': 'Срок',
    'courseApproval.cancel': 'Отмена',
    'courseApproval.submit': 'Отправить запрос',
    'courseApproval.send': 'Отправить на согласование',
    'courseApproval.sendDescription': 'Описание',
  }[key] || key) }),
}));

import { ApprovalRequestModal } from '@/components/course-approval/ApprovalRequestModal';

interface ReviewerListResponse { users: Array<{ id: string; role: string; is_active?: boolean; full_name?: string; first_name?: string; last_name?: string }>; total: number; page: number; per_page: number }

describe('approval reviewer loading', () => {
  beforeEach(() => {
    getMock.mockReset();
    freezeMock.mockReset().mockResolvedValue({ id: 'revision-1' });
    createMock.mockReset().mockResolvedValue({ access_credentials: [] });
  });

  it('reads paginated users and keeps only active methodologists without duplicates', async () => {
    const firstPage = [
      { id: 'admin-1', role: 'admin', is_active: true, full_name: 'Admin' },
      { id: 'inactive-1', role: 'methodologist', is_active: false, full_name: 'Inactive' },
      { id: 'missing-active', role: 'methodologist', full_name: 'Missing Active' },
      { id: 'methodologist-1', role: 'methodologist', is_active: true, full_name: 'Methodologist One' },
      ...Array.from({ length: 96 }, (_, index) => ({ id: `admin-${index + 2}`, role: 'admin', is_active: true, full_name: `Admin ${index + 2}` })),
    ];
    getMock
      .mockResolvedValueOnce({ data: { users: firstPage, total: 102, page: 1, per_page: 100 } })
      .mockResolvedValueOnce({ data: { users: [
        { id: 'methodologist-1', role: 'methodologist', is_active: true, full_name: 'Methodologist One' },
        { id: 'methodologist-2', role: 'methodologist', is_active: true, first_name: 'Methodologist', last_name: 'Two', email: 'two@example.test' },
      ], total: 102, page: 2, per_page: 100 } });
    render(<ApprovalRequestModal open courseId="course-1" onClose={() => undefined} />);

    expect(await screen.findByText('Methodologist One')).toBeInTheDocument();
    expect(screen.getByText('Methodologist Two')).toBeInTheDocument();
    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
    expect(screen.queryByText('Inactive')).not.toBeInTheDocument();
    expect(screen.queryByText('Missing Active')).not.toBeInTheDocument();
    expect(screen.getAllByRole('checkbox')).toHaveLength(2);
    expect(getMock).toHaveBeenNthCalledWith(1, '/v1/users?page=1&per_page=100&is_active=true&role=methodologist');
    expect(getMock).toHaveBeenNthCalledWith(2, '/v1/users?page=2&per_page=100&is_active=true&role=methodologist');
  });

  it('shows a retryable failure instead of treating a failed load as empty', async () => {
    getMock.mockRejectedValueOnce(new Error('network'));
    render(<ApprovalRequestModal open courseId="course-1" onClose={() => undefined} />);

    expect(await screen.findByText('Не удалось открыть согласование.')).toBeInTheDocument();
    getMock.mockResolvedValueOnce({ data: { users: [{ id: 'methodologist-1', role: 'methodologist', is_active: true, full_name: 'Recovered' }], total: 1, page: 1, per_page: 100 } });
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Recovered')).toBeInTheDocument();
  });

  it('submits only the selected eligible canonical identity using personal-link delivery', async () => {
    getMock.mockResolvedValue({ data: { users: [{ id: 'eligible-reviewer', role: 'methodologist', is_active: true, first_name: 'QA', last_name: 'Reviewer' }], total: 1, page: 1, per_page: 100 } });
    render(<ApprovalRequestModal open courseId="course-1" onClose={() => undefined} />);
    fireEvent.click(await screen.findByRole('checkbox', { name: /QA Reviewer/ }));
    fireEvent.click(screen.getByRole('radio', { name: 'Ссылка и PIN' }));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    await waitFor(() => expect(createMock).toHaveBeenCalledWith('revision-1', ['eligible-reviewer'], 'personal_link', undefined, []));
    expect(freezeMock).toHaveBeenCalledExactlyOnceWith('course-1');
  });

  it('does not let a prior course response populate a newly opened scope', async () => {
    let resolveFirst: ((value: { data: ReviewerListResponse }) => void) | undefined;
    getMock.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    getMock.mockResolvedValueOnce({ data: { users: [{ id: 'new-reviewer', role: 'methodologist', is_active: true, full_name: 'New Course Reviewer' }], total: 1, page: 1, per_page: 100 } });
    const view = render(<ApprovalRequestModal open courseId="course-1" onClose={() => undefined} />);
    view.rerender(<ApprovalRequestModal open courseId="course-2" onClose={() => undefined} />);
    expect(await screen.findByText('New Course Reviewer')).toBeInTheDocument();
    resolveFirst?.({ data: { users: [{ id: 'old-reviewer', role: 'methodologist', is_active: true, full_name: 'Old Course Reviewer' }], total: 1, page: 1, per_page: 100 } });
    await waitFor(() => expect(screen.queryByText('Old Course Reviewer')).not.toBeInTheDocument());
  });

  it('surfaces incomplete pagination instead of accepting a short page', async () => {
    getMock
      .mockResolvedValueOnce({ data: { users: [{ id: 'methodologist-1', role: 'methodologist', is_active: true, full_name: 'Only Reviewer' }], total: 2, page: 1, per_page: 100 } })
      .mockResolvedValueOnce({ data: { users: [], total: 2, page: 2, per_page: 100 } });
    render(<ApprovalRequestModal open courseId="course-1" onClose={() => undefined} />);

    expect(await screen.findByText('Не удалось открыть согласование.')).toBeInTheDocument();
    expect(screen.queryByText('Only Reviewer')).not.toBeInTheDocument();
  });

  it('clears the selected reviewer when reopened for another course', async () => {
    getMock.mockResolvedValue({ data: { users: [{ id: 'methodologist-1', role: 'methodologist', is_active: true, full_name: 'Reviewer' }], total: 1, page: 1, per_page: 100 } });
    const view = render(<ApprovalRequestModal open courseId="course-1" onClose={() => undefined} />);
    const checkbox = await screen.findByRole('checkbox');
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    view.rerender(<ApprovalRequestModal open={false} courseId="course-1" onClose={() => undefined} />);
    view.rerender(<ApprovalRequestModal open courseId="course-2" onClose={() => undefined} />);
    expect(await screen.findByRole('checkbox')).not.toBeChecked();
  });
});
