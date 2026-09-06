import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TrainingOverview } from '@/components/admin/TrainingOverview';

const mock = vi.hoisted(() => ({ get: vi.fn(), auth: { accessToken: 'test-token', user: { role: 'methodologist', tenant_id: 'synthetic-a', user_id: 'synthetic-user' } } }));
vi.mock('@/lib/api', () => ({ api: { get: mock.get } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: () => mock.auth }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: 'ru' }) }));

beforeEach(() => { mock.get.mockReset(); mock.auth.user.role = 'methodologist'; mock.auth.user.tenant_id = 'synthetic-a'; });

describe('real training summary consumer', () => {
  it('shows actual counts and keeps absent overdue count unknown', async () => {
    mock.get.mockResolvedValue({ data: { assigned: 3, in_progress: 2 } });
    render(<TrainingOverview />);
    expect(await screen.findByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.getByRole('link')).toHaveAttribute('href', '/training-log');
  });
  it('reports failure without making up zeros', async () => {
    mock.get.mockRejectedValue(new Error('unavailable'));
    render(<TrainingOverview />);
    expect(await screen.findByRole('status')).toHaveTextContent('Сводка недоступна');
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });
  it('does not request training data for a tenant admin', () => {
    mock.auth.user.role = 'admin';
    const { container } = render(<TrainingOverview />);
    expect(container).toBeEmptyDOMElement();
    expect(mock.get).not.toHaveBeenCalled();
  });
  it('ignores the previous tenant response after switching identity', async () => {
    let resolveOld!: (data: unknown) => void;
    mock.get.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    mock.get.mockResolvedValueOnce({ data: { assigned: 1, in_progress: 0, overdue: 0 } });
    const { rerender } = render(<TrainingOverview />);
    mock.auth.user = { ...mock.auth.user, tenant_id: 'synthetic-b' };
    rerender(<TrainingOverview />);
    expect(await screen.findByText('1')).toBeInTheDocument();
    await act(async () => resolveOld({ data: { assigned: 99, in_progress: 99, overdue: 99 } }));
    expect(screen.queryByText('99')).not.toBeInTheDocument();
    expect(mock.get.mock.calls[0][1].signal.aborted).toBe(true);
  });
});
