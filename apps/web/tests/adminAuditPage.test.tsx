import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AuditLogPage from '@/app/admin/audit/page';

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
const toastMock = vi.hoisted(() => ({ error: vi.fn() }));

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/components/ui/Toast', () => ({ toast: toastMock }));

describe('admin audit log', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockImplementation((url: string) => {
      if (url.startsWith('/v1/audit/logs')) {
        return Promise.resolve({ data: [{
          id: 'audit-1', user_id: 'actor-1', actor_email: 'admin@example.test',
          actor_name: 'QA Администратор', action: 'employee_terminated',
          resource_type: 'employee', resource_id: 'employee-1',
          details: { reason: 'Синтетическая проверка' }, created_at: '2026-08-30T08:00:00Z',
        }] });
      }
      if (url === '/v1/users?per_page=500') return Promise.reject({ response: { status: 403 } });
      throw new Error(`Unexpected request: ${url}`);
    });
  });

  it('keeps audit entries usable when the optional account directory is unavailable', async () => {
    render(<AuditLogPage />);

    expect((await screen.findAllByText('Сотрудник уволен')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Причина: Синтетическая проверка')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /QA Администратор/ })).toBeInTheDocument();
    await waitFor(() => expect(toastMock.error).not.toHaveBeenCalled());
    expect(apiMock.get).toHaveBeenCalledWith('/v1/users?per_page=500');
  });
});
