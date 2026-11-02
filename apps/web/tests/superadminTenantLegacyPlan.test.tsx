import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import TenantDetails from '@/app/admin/super/tenants/[id]/page';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'tenant-test' }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.get.mockImplementation((path: string) => Promise.resolve({ data: path.endsWith('/admins') ? [] : {
    id: 'tenant-test', name: 'Test', slug: 'test', status: 'active', plan: 'custom',
    is_financial_organization: false, max_users: 50, max_courses_per_month: 10,
    trial_ends_at: null, paid_until: null, notes: null, created_at: '2026-01-01',
    updated_at: '2026-01-01', settings: {},
  } }));
  apiMock.patch.mockResolvedValue({ data: {} });
  useAuthStore.setState({ accessToken: 'token', user: {
    user_id: 'admin', tenant_id: null, tenant: null, telegram_id: '', role: 'superadmin',
    roles: ['superadmin'], full_name: 'Admin', email: 'admin@example.test',
  } });
});

it('displays the stored legacy plan and submits only changed fields', async () => {
  render(<TenantDetails />);
  const plan = await screen.findByLabelText('Тариф');
  expect(plan).toHaveValue('custom');
  fireEvent.change(plan, { target: { value: 'free' } });
  fireEvent.change(plan, { target: { value: 'custom' } });
  expect(plan).toHaveValue('custom');
  fireEvent.change(screen.getByLabelText('Лимит курсов в месяц'), { target: { value: '50' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /Финансовая организация/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(apiMock.patch).toHaveBeenCalledWith('/v1/admin/super/tenants/tenant-test', {
    max_courses_per_month: 50, is_financial_organization: true,
  }));
});

it('submits a plan when the administrator explicitly changes it', async () => {
  render(<TenantDetails />);
  const plan = await screen.findByLabelText('Тариф');
  fireEvent.change(plan, { target: { value: 'pro' } });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(apiMock.patch).toHaveBeenCalledWith('/v1/admin/super/tenants/tenant-test', {
    plan: 'pro',
  }));
});
