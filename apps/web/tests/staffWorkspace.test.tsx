import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { StaffWorkspace } from '@/features/staff-structure/StaffWorkspace';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const getMock = vi.mocked(api.get);
const postMock = vi.mocked(api.post);

const overview = {
  units: [
    {
      id: 'root-1',
      name: 'Головной офис',
      parent_id: null,
      unit_type: 'organization',
      is_active: true,
      is_head_office: true,
      head_user_id: null,
      breadcrumb: ['Головной офис'],
      direct_count: 1,
      subtree_count: 2,
      hr_managed: false,
    },
    {
      id: 'unit-1',
      name: 'Отдел продаж',
      parent_id: 'root-1',
      unit_type: 'department',
      is_active: true,
      is_head_office: false,
      head_user_id: null,
      breadcrumb: ['Головной офис', 'Отдел продаж'],
      direct_count: 1,
      subtree_count: 1,
      hr_managed: false,
    },
  ],
  positions: [
    { id: 'position-1', name: 'Менеджер', department_id: 'unit-1', is_active: true, employee_count: 1, unit_counts: { 'unit-1': 1 } },
    { id: 'position-2', name: 'Менеджер', department_id: null, is_active: true, employee_count: 0, unit_counts: {} },
  ],
  total: 2,
  unplaced_count: 0,
};

const employee = {
  id: 'employee-1',
  full_name: 'Айгерим Садыкова',
  personnel_number: 'EMP-001',
  is_active: true,
  organization_unit_id: 'unit-1',
  effective_unit_id: 'unit-1',
  placement_source: 'explicit',
  position_id: 'position-1',
  position_name: 'Менеджер',
  hr_managed: false,
};

const roster = {
  items: [employee],
  total: 1,
  page: 1,
  page_size: 20,
};

const defaultProps = {
  onAddEmployee: vi.fn(),
  onEditEmployee: vi.fn(),
  onEditUnit: vi.fn(),
  onAddUnit: vi.fn(),
  refreshKey: 0,
};

const authUser = {
  user_id: 'actor-1',
  tenant_id: 'tenant-1',
  role: 'methodologist',
  full_name: 'Synthetic Methodologist',
  email: 'methodologist@example.test',
};

function installHappyReads() {
  getMock.mockImplementation(async (url: string) => {
    if (url === '/v1/organization-units/workspace') return { data: overview } as any;
    if (url === '/v1/organization-units/employees') return { data: roster } as any;
    throw new Error(`Unexpected GET ${url}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  useAuthStore.setState({ accessToken: 'synthetic-token', user: authUser as any, initialized: true });
  window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=schema&staff_unit=all&staff_scope=subtree&staff_access=active&staff_page=1');
  installHappyReads();
});

describe('StaffWorkspace', () => {
  it('uses the canonical workspace and server-roster routes and keeps navigation in the URL', async () => {
    render(<StaffWorkspace {...defaultProps} />);

    expect(await screen.findByRole('button', { name: 'Открыть подразделение: Головной офис' })).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith(
      '/v1/organization-units/workspace',
      expect.objectContaining({ params: { access: 'active' } }),
    );
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith(
        '/v1/organization-units/employees',
        expect.objectContaining({
          params: expect.objectContaining({
            scope: 'subtree',
            access: 'active',
            page: 1,
            page_size: 20,
          }),
        }),
      );
    });

    fireEvent.click(screen.getByRole('button', { name: 'Открыть подразделение: Головной офис' }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('staff_unit')).toBe('root-1'));

    const schemaTab = screen.getByRole('tab', { name: 'Схема' });
    fireEvent.keyDown(schemaTab, { key: 'ArrowRight' });
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Сотрудники' })).toHaveAttribute('aria-selected', 'true'));
    expect(new URLSearchParams(window.location.search).get('staff_view')).toBe('people');
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('structure');
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Сотрудники' })));

    window.history.pushState({}, '', '/admin/staff?tab=structure&staff_view=schema&staff_unit=unplaced&staff_scope=direct&staff_access=all&staff_page=1');
    act(() => window.dispatchEvent(new PopStateEvent('popstate')));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Подразделение' })).toHaveValue('unplaced'));
  });

  it('previews an employee transfer, confirms only the frozen plan id, and refreshes after success', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unit-1&staff_scope=direct&staff_access=active&staff_page=1');
    postMock.mockImplementation(async (url: string, body: unknown) => {
      if (url === '/v1/organization-units/changes/preview') {
        expect(body).toEqual({
          kind: 'employee',
          target_id: 'employee-1',
          organization_unit_id: null,
          position_id: 'position-1',
          reason: 'Смена команды',
        });
        return {
          data: {
            id: 'plan-1',
            expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
            kind: 'employee',
            target_id: 'employee-1',
            from_path: ['Головной офис', 'Отдел продаж'],
            to_path: ['Головной офис'],
            affected_employees: 1,
            training: {
              added: 2,
              no_longer_required: 1,
              preserved_completed: 3,
              preserved_other_sources: 4,
              courses: [{
                course_id: 'course-1',
                title: 'Безопасность продаж',
                added: 2,
                retained_previous: 1,
              }],
            },
            reporting: [{
              user_id: 'methodologist-2',
              full_name: 'Методист Два',
              before_count: 4,
              after_count: 5,
              gained: 1,
              lost: 0,
            }],
            warnings: ['Проверьте новый путь'],
          },
        } as any;
      }
      if (url === '/v1/organization-units/changes/plan-1/confirm') {
        expect(body).toEqual({ confirmed: true });
        return {
          data: {
            plan_id: 'plan-1',
            status: 'succeeded',
            affected_employees: 1,
            added: 2,
            preserved: 7,
            executed_at: '2026-10-17T12:00:00Z',
          },
        } as any;
      }
      throw new Error(`Unexpected POST ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);
    fireEvent.click(await screen.findByRole('button', { name: /Перевести/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Безопасный перевод сотрудника' });
    fireEvent.change(within(dialog).getByLabelText('Новое подразделение'), { target: { value: '' } });
    fireEvent.change(within(dialog).getByLabelText('Причина изменения'), { target: { value: 'Смена команды' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Получить предпросмотр' }));

    expect(await within(dialog).findByText('Предпросмотр зафиксирован')).toBeInTheDocument();
    expect(within(dialog).getByText('Будет добавлено:')).toHaveTextContent('2');
    expect(within(dialog).getByText('Безопасность продаж')).toBeInTheDocument();
    expect(within(dialog).getByText(/Прежних назначений сохранено: 1/)).toBeInTheDocument();
    expect(within(dialog).getByText(/означают утрату требования, а не удаление/)).toBeInTheDocument();
    expect(within(dialog).getByText('Методист Два')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить этот предпросмотр' }));

    expect(await within(dialog).findByText('Изменение выполнено')).toBeInTheDocument();
    expect(postMock).toHaveBeenCalledWith(
      '/v1/organization-units/changes/plan-1/confirm',
      { confirmed: true },
    );
    await waitFor(() => expect(getMock.mock.calls.filter(([url]) => url === '/v1/organization-units/workspace').length).toBeGreaterThan(1));
  });

  it('requires a fresh preview after confirmation fails', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unit-1&staff_scope=direct&staff_access=active&staff_page=1');
    postMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/changes/preview') return {
        data: {
          id: 'plan-stale',
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          kind: 'employee',
          target_id: 'employee-1',
          from_path: ['Отдел продаж'],
          to_path: ['Головной офис'],
          affected_employees: 1,
          training: { added: 0, no_longer_required: 0, preserved_completed: 0, preserved_other_sources: 0, courses: [] },
          reporting: [],
          warnings: [],
        },
      } as any;
      if (url === '/v1/organization-units/changes/plan-stale/confirm') {
        throw { response: { data: { detail: 'preview_stale' }, status: 409 } };
      }
      throw new Error(`Unexpected POST ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);
    fireEvent.click(await screen.findByRole('button', { name: /Перевести/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Причина изменения'), { target: { value: 'Новая команда' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Получить предпросмотр' }));
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Подтвердить этот предпросмотр' }));

    expect(await within(dialog).findByText(/Данные изменились/)).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Подтвердить этот предпросмотр' })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Получить предпросмотр' })).toBeEnabled();
  });

  it('blocks explicitly HR-managed records without calling a mutation route', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unit-1&staff_scope=direct&staff_access=active&staff_page=1');
    getMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/workspace') return {
        data: {
          ...overview,
          units: overview.units.map((unit) => unit.id === 'unit-1' ? { ...unit, hr_managed: true } : unit),
        },
      } as any;
      if (url === '/v1/organization-units/employees') return {
        data: { ...roster, items: [{ ...employee, hr_managed: true }] },
      } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);
    expect(await screen.findByText(/Управляется HR-системой: ручной перевод заблокирован/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Перевести/ })).toBeDisabled();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('ignores a stale roster response after the account-access filter changes', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=all&staff_scope=subtree&staff_access=active&staff_page=1');
    let resolveActive: ((value: unknown) => void) | undefined;
    const activeResponse = new Promise((resolve) => { resolveActive = resolve; });
    const inactiveEmployee = {
      ...employee,
      id: 'employee-inactive',
      full_name: 'Поздний неактивный сотрудник',
      personnel_number: 'EMP-002',
      is_active: false,
    };
    getMock.mockImplementation(async (url: string, config?: unknown) => {
      const access = (config as { params?: { access?: string } } | undefined)?.params?.access;
      if (url === '/v1/organization-units/workspace') return { data: overview } as any;
      if (url === '/v1/organization-units/employees' && access === 'active') return activeResponse as any;
      if (url === '/v1/organization-units/employees' && access === 'inactive') {
        return { data: { ...roster, items: [inactiveEmployee] } } as any;
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);
    fireEvent.change(await screen.findByRole('combobox', { name: 'Доступ к кабинету' }), { target: { value: 'inactive' } });
    expect(await screen.findByText('Поздний неактивный сотрудник')).toBeInTheDocument();

    await act(async () => {
      resolveActive?.({ data: roster });
      await activeResponse;
    });
    expect(screen.queryByText('Айгерим Садыкова')).not.toBeInTheDocument();
    expect(screen.getByText('Поздний неактивный сотрудник')).toBeInTheDocument();
  });

  it('shows a shared position from effective unit counts even when its fallback department differs', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=schema&staff_unit=unit-1&staff_scope=direct&staff_access=active&staff_page=1');
    const sharedOverview = {
      ...overview,
      positions: [{
        id: 'shared-position',
        name: 'Общий HR-специалист',
        department_id: 'root-1',
        is_active: true,
        employee_count: 3,
        unit_counts: { 'root-1': 2, 'unit-1': 1 },
      }],
    };
    getMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/workspace') return { data: sharedOverview } as any;
      if (url === '/v1/organization-units/employees') return { data: roster } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);
    const detailTabs = await screen.findByRole('tablist', { name: 'Содержимое подразделения' });
    fireEvent.click(within(detailTabs).getByRole('tab', { name: 'Должности' }));

    expect(screen.getByText('Общий HR-специалист')).toBeInTheDocument();
    expect(screen.getByText(/В выбранном составе: 1.*Во всей компании.*: 3/)).toBeInTheDocument();
    expect(screen.getByText(/Общая должность используется в нескольких подразделениях/)).toBeInTheDocument();
  });

  it('normalizes an unknown URL unit before the first roster request', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unknown-unit&staff_scope=direct&staff_access=active&staff_page=1');

    render(<StaffWorkspace {...defaultProps} />);

    expect(await screen.findByText('Айгерим Садыкова')).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get('staff_unit')).toBe('all');
    expect(getMock.mock.calls.filter(([url]) => url === '/v1/organization-units/employees')).toHaveLength(1);
  });

  it('keeps inactive units and positions readable but disables them as mutation destinations', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unit-1&staff_scope=direct&staff_access=all&staff_page=1');
    const inactiveOverview = {
      ...overview,
      units: overview.units.map((unit) => unit.id === 'root-1' ? { ...unit, is_active: false } : unit),
      positions: overview.positions.map((position) => position.id === 'position-2' ? { ...position, is_active: false } : position),
    };
    getMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/workspace') return { data: inactiveOverview } as any;
      if (url === '/v1/organization-units/employees') return { data: roster } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);

    const unitFilter = await screen.findByRole('combobox', { name: 'Подразделение' });
    expect(within(unitFilter).getByRole('option', { name: 'Головной офис · неактивно' })).toBeEnabled();
    const positionFilter = screen.getByRole('combobox', { name: 'Должность' });
    expect(within(positionFilter).getByRole('option', { name: /без подразделения · неактивна/ })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: /Перевести/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Безопасный перевод сотрудника' });
    const destinationUnit = within(dialog).getByRole('combobox', { name: 'Новое подразделение' });
    const destinationPosition = within(dialog).getByRole('combobox', { name: 'Должность' });
    expect(within(destinationUnit).getByRole('option', { name: 'Головной офис · неактивно' })).toBeDisabled();
    expect(within(destinationPosition).getByRole('option', { name: /без подразделения · неактивна/ })).toBeDisabled();
  });

  it.each([
    { code: 'ERR_NETWORK', message: 'Network Error' },
    { response: { status: 502, data: {} } },
  ])('locks the dialog and retries the same plan after an unknown outcome: %j', async (failure) => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unit-1&staff_scope=direct&staff_access=active&staff_page=1');
    let rejectFirstConfirm: ((reason?: unknown) => void) | undefined;
    const firstConfirm = new Promise((_resolve, reject) => { rejectFirstConfirm = reject; });
    let confirmCalls = 0;
    postMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/changes/preview') return {
        data: {
          id: 'plan-network-unknown',
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          kind: 'employee',
          target_id: 'employee-1',
          from_path: ['Отдел продаж'],
          to_path: ['Головной офис'],
          affected_employees: 1,
          training: { added: 0, no_longer_required: 0, preserved_completed: 0, preserved_other_sources: 0, courses: [] },
          reporting: [],
          warnings: [],
        },
      } as any;
      if (url === '/v1/organization-units/changes/plan-network-unknown/confirm') {
        confirmCalls += 1;
        if (confirmCalls === 1) return firstConfirm as any;
        return {
          data: {
            plan_id: 'plan-network-unknown',
            status: 'succeeded',
            affected_employees: 1,
            added: 0,
            preserved: 1,
            executed_at: '2026-10-17T12:00:00Z',
          },
        } as any;
      }
      throw new Error(`Unexpected POST ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);
    fireEvent.click(await screen.findByRole('button', { name: /Перевести/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Причина изменения'), { target: { value: 'Проверка сети' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Получить предпросмотр' }));
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Подтвердить этот предпросмотр' }));

    expect(within(dialog).getByRole('button', { name: 'Подтверждение…' })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Отмена' })).toBeDisabled();
    expect(within(dialog).getByLabelText('Причина изменения')).toBeDisabled();

    await act(async () => {
      rejectFirstConfirm?.(failure);
      try { await firstConfirm; } catch { /* the component owns this rejection */ }
    });

    expect(await within(dialog).findByText(/Исход операции неизвестен/)).toHaveTextContent('plan-network-unknown');
    expect(within(dialog).getByText('Предпросмотр зафиксирован')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Отмена' })).toBeDisabled();
    expect(window.sessionStorage).toHaveLength(1);
    expect(window.sessionStorage.getItem(window.sessionStorage.key(0)!)).toBe('plan-network-unknown');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    const backdrop = document.querySelector<HTMLElement>('[data-modal-backdrop="true"]');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    const retry = within(dialog).getByRole('button', { name: 'Повторить подтверждение этого плана' });
    fireEvent.click(retry);

    expect(await within(dialog).findByText('Изменение выполнено')).toBeInTheDocument();
    expect(postMock.mock.calls.filter(([url]) => url === '/v1/organization-units/changes/plan-network-unknown/confirm')).toEqual([
      ['/v1/organization-units/changes/plan-network-unknown/confirm', { confirmed: true }],
      ['/v1/organization-units/changes/plan-network-unknown/confirm', { confirmed: true }],
    ]);
    expect(window.sessionStorage).toHaveLength(0);
  });

  it('restores an unresolved plan after remount and retries the same id only on explicit action', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unit-1&staff_scope=direct&staff_access=active&staff_page=1');
    let confirmCalls = 0;
    postMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/changes/preview') return {
        data: {
          id: 'plan-recover-after-reload',
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          kind: 'employee',
          target_id: 'employee-1',
          from_path: ['Отдел продаж'],
          to_path: ['Головной офис'],
          affected_employees: 1,
          training: { added: 0, no_longer_required: 0, preserved_completed: 0, preserved_other_sources: 0, courses: [] },
          reporting: [],
          warnings: [],
        },
      } as any;
      if (url === '/v1/organization-units/changes/plan-recover-after-reload/confirm') {
        confirmCalls += 1;
        if (confirmCalls === 1) throw { code: 'ERR_NETWORK', message: 'Network Error' };
        return {
          data: {
            plan_id: 'plan-recover-after-reload',
            status: 'succeeded',
            affected_employees: 1,
            added: 0,
            preserved: 1,
            executed_at: '2026-10-17T12:00:00Z',
          },
        } as any;
      }
      throw new Error(`Unexpected POST ${url}`);
    });

    const firstMount = render(<StaffWorkspace {...defaultProps} />);
    fireEvent.click(await screen.findByRole('button', { name: /Перевести/ }));
    let dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Причина изменения'), { target: { value: 'Проверка восстановления' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Получить предпросмотр' }));
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Подтвердить этот предпросмотр' }));
    expect(await within(dialog).findByText(/Исход операции неизвестен/)).toBeInTheDocument();
    expect(confirmCalls).toBe(1);
    firstMount.unmount();

    render(<StaffWorkspace {...defaultProps} />);
    const recovery = await screen.findByRole('alert', { name: '' });
    expect(within(recovery).getByText(/plan-recover-after-reload/)).toBeInTheDocument();
    expect(confirmCalls).toBe(1);

    fireEvent.click(within(recovery).getByRole('button', { name: 'Повторить подтверждение сохранённого плана' }));
    expect(await screen.findByText('Изменение выполнено')).toBeInTheDocument();
    expect(confirmCalls).toBe(2);
    expect(postMock.mock.calls.filter(([url]) => url === '/v1/organization-units/changes/plan-recover-after-reload/confirm')).toEqual([
      ['/v1/organization-units/changes/plan-recover-after-reload/confirm', { confirmed: true }],
      ['/v1/organization-units/changes/plan-recover-after-reload/confirm', { confirmed: true }],
    ]);
    expect(window.sessionStorage).toHaveLength(0);
  });

  it('scopes unresolved confirmation recovery to the authenticated tenant and actor', async () => {
    window.sessionStorage.setItem(
      'staff-structure:pending-confirmation:tenant-1:actor-1',
      'plan-for-actor-1',
    );
    render(<StaffWorkspace {...defaultProps} />);
    expect(await screen.findByText(/plan-for-actor-1/)).toBeInTheDocument();

    act(() => {
      useAuthStore.setState({ user: { ...authUser, user_id: 'actor-2' } as any });
    });
    await waitFor(() => expect(screen.queryByText(/plan-for-actor-1/)).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Повторить подтверждение сохранённого плана' })).not.toBeInTheDocument();
    expect(postMock).not.toHaveBeenCalled();

    act(() => {
      useAuthStore.setState({ user: authUser as any });
    });
    expect(await screen.findByText(/plan-for-actor-1/)).toBeInTheDocument();
  });

  it('does not send confirmation when safe session persistence is unavailable', async () => {
    window.history.replaceState({}, '', '/admin/staff?tab=structure&staff_view=people&staff_unit=unit-1&staff_scope=direct&staff_access=active&staff_page=1');
    postMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/changes/preview') return {
        data: {
          id: 'plan-storage-blocked',
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          kind: 'employee',
          target_id: 'employee-1',
          from_path: ['Отдел продаж'],
          to_path: ['Головной офис'],
          affected_employees: 1,
          training: { added: 0, no_longer_required: 0, preserved_completed: 0, preserved_other_sources: 0, courses: [] },
          reporting: [],
          warnings: [],
        },
      } as any;
      throw new Error(`Unexpected POST ${url}`);
    });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage blocked', 'SecurityError');
    });

    try {
      render(<StaffWorkspace {...defaultProps} />);
      fireEvent.click(await screen.findByRole('button', { name: /Перевести/ }));
      const dialog = await screen.findByRole('dialog');
      fireEvent.change(within(dialog).getByLabelText('Причина изменения'), { target: { value: 'Проверка хранилища' } });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Получить предпросмотр' }));
      fireEvent.click(await within(dialog).findByRole('button', { name: 'Подтвердить этот предпросмотр' }));

      expect(await within(dialog).findByText(/Подтверждение не отправлено/)).toBeInTheDocument();
      expect(postMock.mock.calls.filter(([url]) => String(url).endsWith('/confirm'))).toHaveLength(0);
    } finally {
      setItem.mockRestore();
    }
  });

  it('does not display old overview counts while a new access filter is loading', async () => {
    let resolveInactiveOverview: ((value: unknown) => void) | undefined;
    const pendingInactiveOverview = new Promise((resolve) => { resolveInactiveOverview = resolve; });
    const filteredOverview = {
      ...overview,
      total: 1,
      units: overview.units.map((unit) => ({ ...unit, direct_count: 0, subtree_count: 1 })),
    };
    getMock.mockImplementation(async (url: string, config?: unknown) => {
      const access = (config as { params?: { access?: string } } | undefined)?.params?.access;
      if (url === '/v1/organization-units/workspace' && access === 'inactive') return pendingInactiveOverview as any;
      if (url === '/v1/organization-units/workspace') return { data: overview } as any;
      if (url === '/v1/organization-units/employees') return { data: roster } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<StaffWorkspace {...defaultProps} />);
    expect(await screen.findByTestId('staff-overview-total')).toHaveTextContent('2');

    fireEvent.change(screen.getByRole('combobox', { name: 'Доступ к кабинету' }), { target: { value: 'inactive' } });
    expect(await screen.findByText('Загрузка структуры и сотрудников…')).toBeInTheDocument();
    expect(screen.queryByTestId('staff-overview-total')).not.toBeInTheDocument();

    await act(async () => {
      resolveInactiveOverview?.({ data: filteredOverview });
      await pendingInactiveOverview;
    });
    expect(await screen.findByTestId('staff-overview-total')).toHaveTextContent('1');
  });
});
