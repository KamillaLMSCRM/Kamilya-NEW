import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const cancelMock = vi.hoisted(() => vi.fn());
const resendMock = vi.hoisted(() => vi.fn());
const revokeMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/courseApproval', () => ({ cancelApprovalRequest: cancelMock, resendApprovalDelivery: resendMock, revokeApprovalAccess: revokeMock }));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ApprovalStatusPanel } from '@/components/course-approval/ApprovalStatusPanel';
import type { ReviewerApprovalStatus } from '@/lib/courseApproval';

const request = {
  request_id: 'request-1',
  revision_id: 'revision-1',
  revision_number: 2,
  outcome: 'pending' as const,
  delivery_mode: 'personal_link' as const,
  reviewer_ids: ['reviewer-1'],
};

describe('approval request actions', () => {
  beforeEach(() => {
    cancelMock.mockReset().mockResolvedValue(undefined);
    resendMock.mockReset().mockResolvedValue({ request_id: 'request-1', rotated: true, retried: 0, access_credentials: [{ reviewer_id: 'reviewer-1', access_url: 'https://example.test/new', temporary_pin: '654321', expires_at: '2027-01-01T00:00:00Z' }] });
    revokeMock.mockReset().mockResolvedValue(undefined);
  });

  it('confirms cancellation in-app and visibly marks the request cancelled', async () => {
    render(<ApprovalStatusPanel requests={[request]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Отменить запрос' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(document.querySelector('[data-modal-backdrop="true"]') as HTMLElement);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Отменить запрос' })[1]);
    await waitFor(() => expect(screen.getByText('Запрос отменён')).toBeInTheDocument());
    expect(cancelMock).toHaveBeenCalledWith('request-1');
  });

  it('shows rotated URL and PIN once in a non-dismissible confirmation panel', async () => {
    render(<ApprovalStatusPanel requests={[request]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Сменить доступ' }));
    expect(screen.getByRole('dialog')).toHaveTextContent(/новый секрет будет показан один раз/i);
    fireEvent.click(document.querySelector('[data-modal-backdrop="true"]') as HTMLElement);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Сменить доступ' })[1]);
    await waitFor(() => expect(screen.getByText('https://example.test/new')).toBeInTheDocument());
    expect(screen.getByText('654321')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Я скопировал данные — закрыть' }));
    expect(screen.queryByText('https://example.test/new')).not.toBeInTheDocument();
    expect(resendMock).toHaveBeenCalledWith('request-1', true);
  });

  it('keeps the confirmation open and exposes API failures accessibly', async () => {
    cancelMock.mockRejectedValueOnce(new Error('network down'));
    render(<ApprovalStatusPanel requests={[request]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Отменить запрос' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Отменить запрос' })[1]);
    expect(await screen.findByRole('alert')).toHaveTextContent('network down');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('localizes known reviewer status enums without exposing their wire values', () => {
    render(<ApprovalStatusPanel requests={[{
      ...request,
      work_items: [{
        reviewer_id: 'reviewer-1',
        delivery_state: 'queued',
        access_state: 'pin_verified',
        activity_state: 'not_started',
        deadline_state: 'overdue',
        outcome: 'changes_requested',
      }],
    }]} readOnly />);

    expect(screen.getByText('В очереди')).toBeInTheDocument();
    expect(screen.getByText('PIN подтверждён')).toBeInTheDocument();
    expect(screen.getByText('Не начато')).toBeInTheDocument();
    expect(screen.getByText(/Просрочено/)).toBeInTheDocument();
    expect(screen.getByText('Нужны изменения')).toBeInTheDocument();
    expect(screen.queryByText('queued')).not.toBeInTheDocument();
    expect(screen.queryByText('pin_verified')).not.toBeInTheDocument();
    expect(screen.queryByText('not_started')).not.toBeInTheDocument();
    expect(screen.queryByText('overdue')).not.toBeInTheDocument();
    expect(screen.queryByText('changes_requested')).not.toBeInTheDocument();
  });

  it('keeps unknown and prototype-looking status values as raw fallback text', () => {
    render(<ApprovalStatusPanel requests={[{
      ...request,
      work_items: [
        { reviewer_id: 'reviewer-1', delivery_state: 'toString' } as unknown as ReviewerApprovalStatus,
        { reviewer_id: 'reviewer-2', delivery_state: 'future_status' } as unknown as ReviewerApprovalStatus,
      ],
    }]} readOnly />);

    expect(screen.getByText('toString')).toBeInTheDocument();
    expect(screen.getByText('future_status')).toBeInTheDocument();
  });

  it('labels terminal delivery as a permanent failure rather than completion', () => {
    render(<ApprovalStatusPanel requests={[{
      ...request,
      work_items: [{ reviewer_id: 'reviewer-1', delivery_state: 'terminal' }],
    }]} readOnly />);

    expect(screen.getByText('Постоянная ошибка доставки')).toBeInTheDocument();
  });
});
