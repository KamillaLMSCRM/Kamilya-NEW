import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AdminStaffPage from '@/app/admin/staff/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: (url: string) => window.history.replaceState({}, '', url),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const getMock = vi.mocked(api.get);
const postMock = vi.mocked(api.post);

const user = {
  user_id: 'methodologist-1',
  tenant_id: 'tenant-1',
  tenant: { id: 'tenant-1', name: 'Сандык' },
  telegram_id: '',
  role: 'methodologist',
  roles: ['methodologist'],
  full_name: 'Методист',
  email: 'methodologist@example.com',
};

const tree = {
  branches: [{
    id: 'office-1',
    name: 'Центральный офис',
    unit_type: 'organization',
    is_head_office: true,
    children: [{
      id: 'unit-1',
      name: 'Команда продукта',
      unit_type: 'team',
      parent_id: 'office-1',
      children: [],
      positions: [],
    }],
    positions: [],
  }],
  legacy_roots: [],
  unassigned_legacy_positions: [],
  summary: { total_branches: 1, total_departments: 1, total_positions: 0, total_employees: 0 },
};

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'test-token', user });
  window.history.replaceState({}, '', '/');
  getMock.mockImplementation(async (url: string) => {
    if (url.includes('/import/mappings')) return { data: [] } as any;
    if (url === '/v1/departments') return { data: { departments: [] } } as any;
    if (url === '/v1/positions') return { data: [
      { id: 'position-without-unit', name: 'Директор без подразделения', department: null, department_id: null },
    ] } as any;
    if (url.includes('/organization-units/tree')) return { data: tree } as any;
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('manual staff organization unit contract', () => {
  it('allows an employee with a required existing position and no organization unit', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('button', { name: /Добавить сотрудника/i }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });

    fireEvent.change(within(dialog).getByLabelText(/^Табельный номер/), { target: { value: 'EMP-UNIT-OPTIONAL' } });
    fireEvent.change(within(dialog).getByLabelText(/^Имя/), { target: { value: 'Алия' } });
    fireEvent.change(within(dialog).getByLabelText(/^Фамилия/), { target: { value: 'Садыкова' } });
    fireEvent.change(within(dialog).getByRole('combobox', { name: /^Должность/ }), { target: { value: 'position-without-unit' } });

    postMock.mockResolvedValueOnce({ data: { created: 1, updated: 0, skipped: 0, positions_created: 0 } } as any);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Добавить' }));

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/admin/staff/manual',
      expect.objectContaining({
        position_id: 'position-without-unit',
        organization_unit_id: undefined,
        department_id: undefined,
      }),
    ));
  });

  it('submits the explicitly selected generic unit without using legacy department_id', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('button', { name: /Добавить сотрудника/i }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });

    const unitSelect = await within(dialog).findByRole('combobox', { name: /^Отдел/ });
    await within(unitSelect).findByRole('option', { name: /Команда продукта/ });
    fireEvent.change(unitSelect, { target: { value: 'unit-1' } });
    fireEvent.change(within(dialog).getByLabelText(/^Табельный номер/), { target: { value: 'EMP-UNIT-1' } });
    fireEvent.change(within(dialog).getByLabelText(/^Имя/), { target: { value: 'Иван' } });
    fireEvent.change(within(dialog).getByLabelText(/^Фамилия/), { target: { value: 'Петров' } });
    fireEvent.change(within(dialog).getByRole('combobox', { name: /^Должность/ }), { target: { value: 'position-without-unit' } });

    postMock.mockResolvedValueOnce({ data: { created: 1, updated: 0, skipped: 0, positions_created: 0 } } as any);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Добавить' }));

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/admin/staff/manual',
      expect.objectContaining({
        position_id: 'position-without-unit',
        organization_unit_id: 'unit-1',
        department_id: undefined,
      }),
    ));
  });
});
