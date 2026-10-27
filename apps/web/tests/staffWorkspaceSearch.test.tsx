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
      direct_count: 21,
      subtree_count: 41,
      hr_managed: false,
    },
    {
      id: 'unit-sales',
      name: 'Отдел продаж',
      parent_id: 'root-1',
      unit_type: 'department',
      is_active: true,
      is_head_office: false,
      head_user_id: null,
      breadcrumb: ['Головной офис', 'Отдел продаж'],
      direct_count: 20,
      subtree_count: 20,
      hr_managed: false,
    },
  ],
  positions: [
    {
      id: 'position-manager',
      name: 'Менеджер',
      department_id: 'unit-sales',
      is_active: true,
      employee_count: 20,
      unit_counts: { 'unit-sales': 20 },
    },
  ],
  total: 41,
  unplaced_count: 0,
};

const pageEmployee = {
  id: 'employee-page-3',
  full_name: 'Сотрудник Третьей Страницы',
  personnel_number: 'EMP-041',
  is_active: true,
  organization_unit_id: 'root-1',
  effective_unit_id: 'root-1',
  placement_source: 'explicit',
  position_id: null,
  position_name: null,
  hr_managed: false,
};

const surnameMatch = {
  id: 'employee-tanabayeva',
  full_name: 'Алия Танабаева',
  personnel_number: 'EMP-019',
  is_active: true,
  organization_unit_id: 'unit-sales',
  effective_unit_id: 'unit-sales',
  placement_source: 'explicit',
  position_id: 'position-manager',
  position_name: 'Менеджер',
  hr_managed: false,
};

const defaultProps = {
  onAddEmployee: vi.fn(),
  onEditEmployee: vi.fn(),
  onEditUnit: vi.fn(),
  onAddUnit: vi.fn(),
  onArchiveUnit: vi.fn(),
  refreshKey: 0,
};

type RosterParams = {
  unit_id?: string;
  scope?: string;
  access?: string;
  q?: string;
  position_id?: string;
  missing_position?: boolean;
  page?: number;
  page_size?: number;
};

function rosterParams(): RosterParams[] {
  return getMock.mock.calls
    .filter(([url]) => url === '/v1/organization-units/employees')
    .map(([, config]) => (config as { params: RosterParams }).params);
}

function latestRosterParams(): RosterParams {
  return rosterParams().at(-1) || {};
}

function installRosterReads(
  resolveRoster: (params: RosterParams) => unknown = (params) => {
    if (params.q?.toLocaleLowerCase() === 'танаб') {
      return { items: [surnameMatch], total: 1, page: 1, page_size: 20 };
    }
    return { items: [pageEmployee], total: 41, page: params.page || 1, page_size: 20 };
  },
): void {
  getMock.mockImplementation(async (url: string, config?: unknown) => {
    if (url === '/v1/organization-units/workspace') return { data: overview } as never;
    if (url === '/v1/organization-units/employees') {
      const params = (config as { params: RosterParams }).params;
      return { data: resolveRoster(params) } as never;
    }
    throw new Error(`Unexpected GET ${url}`);
  });
}

async function openPeopleWorkspace(): Promise<HTMLInputElement> {
  return screen.findByRole('searchbox', { name: /поиск/i });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  useAuthStore.setState({
    accessToken: 'synthetic-token',
    initialized: true,
    user: {
      user_id: 'methodologist-1',
      tenant_id: 'tenant-1',
      role: 'methodologist',
      roles: ['methodologist'],
      full_name: 'Synthetic Methodologist',
      email: 'methodologist@example.test',
    } as never,
  });
  window.history.replaceState(
    {},
    '',
    '/staff?tab=structure&staff_view=people&staff_unit=all&staff_scope=subtree&staff_access=active&staff_page=3',
  );
  installRosterReads();
});

describe('StaffWorkspace employee search', () => {
  it('debounces a lowercase surname fragment into a fresh server query from page one', async () => {
    render(<StaffWorkspace {...defaultProps} />);
    expect(await screen.findByText(pageEmployee.full_name)).toBeInTheDocument();

    const search = await openPeopleWorkspace();
    fireEvent.change(search, { target: { value: 'танаб' } });

    expect(latestRosterParams()).not.toMatchObject({ q: 'танаб' });
    expect(await screen.findByText(surnameMatch.full_name, {}, { timeout: 1_500 })).toBeInTheDocument();
    expect(latestRosterParams()).toMatchObject({ q: 'танаб', page: 1, page_size: 20 });
    expect(screen.queryByText(pageEmployee.full_name)).not.toBeInTheDocument();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('submits immediately with the visible Find action without waiting for debounce', async () => {
    render(<StaffWorkspace {...defaultProps} />);
    await screen.findByText(pageEmployee.full_name);

    fireEvent.change(await openPeopleWorkspace(), { target: { value: 'танаб' } });
    fireEvent.click(screen.getByRole('button', { name: 'Найти' }));

    await waitFor(() => expect(latestRosterParams()).toMatchObject({ q: 'танаб', page: 1 }));
    expect(await screen.findByText(surnameMatch.full_name)).toBeInTheDocument();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('restores query and position from the URL and follows Back/Forward state', async () => {
    window.history.replaceState(
      {},
      '',
      '/staff?tab=structure&staff_view=people&staff_unit=unit-sales&staff_scope=direct&staff_access=all&staff_q=%D1%82%D0%B0%D0%BD%D0%B0%D0%B1&staff_position=position-manager&staff_page=2',
    );
    installRosterReads((params) => ({
      items: [surnameMatch],
      total: 41,
      page: params.page || 1,
      page_size: 20,
    }));
    render(<StaffWorkspace {...defaultProps} />);

    expect(await openPeopleWorkspace()).toHaveValue('танаб');
    expect(screen.getByRole('combobox', { name: 'Должность' })).toHaveValue('position-manager');
    await waitFor(() => expect(latestRosterParams()).toMatchObject({
      unit_id: 'unit-sales',
      scope: 'direct',
      access: 'all',
      q: 'танаб',
      position_id: 'position-manager',
      page: 2,
    }));

    window.history.pushState(
      {},
      '',
      '/staff?tab=structure&staff_view=people&staff_unit=all&staff_scope=subtree&staff_access=active&staff_q=%D1%81%D0%B0%D0%B4&staff_position=missing&staff_page=1',
    );
    act(() => window.dispatchEvent(new PopStateEvent('popstate')));

    await waitFor(() => expect(screen.getByRole('searchbox', { name: /поиск/i })).toHaveValue('сад'));
    expect(screen.getByRole('combobox', { name: 'Должность' })).toHaveValue('missing');
    await waitFor(() => expect(latestRosterParams()).toMatchObject({
      scope: 'subtree',
      access: 'active',
      q: 'сад',
      missing_position: true,
      page: 1,
    }));
  });

  it('makes selected-subtree scope visible and can widen the same query to all employees', async () => {
    window.history.replaceState(
      {},
      '',
      '/staff?tab=structure&staff_view=people&staff_unit=unit-sales&staff_scope=direct&staff_access=active&staff_q=%D1%82%D0%B0%D0%BD%D0%B0%D0%B1&staff_position=position-manager&staff_page=1',
    );
    render(<StaffWorkspace {...defaultProps} />);
    await screen.findByText(surnameMatch.full_name);

    expect(screen.getByText('Где ищем: Головной офис → Отдел продаж')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Искать среди всех сотрудников' }));

    await waitFor(() => expect(latestRosterParams()).toMatchObject({
      scope: 'subtree',
      access: 'all',
      q: 'танаб',
      page: 1,
    }));
    expect(latestRosterParams().unit_id).toBeUndefined();
    expect(latestRosterParams().position_id).toBeUndefined();
    const params = new URLSearchParams(window.location.search);
    expect(params.get('staff_unit')).toBe('all');
    expect(params.get('staff_access')).toBe('all');
    expect(params.get('staff_q')).toBe('танаб');
    expect(params.get('staff_position')).toBeNull();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('normalizes a stale position URL before issuing a roster request', async () => {
    window.history.replaceState(
      {},
      '',
      '/staff?tab=structure&staff_view=people&staff_unit=all&staff_scope=subtree&staff_access=active&staff_position=position-deleted&staff_page=1',
    );
    render(<StaffWorkspace {...defaultProps} />);

    await screen.findByText(pageEmployee.full_name);
    await waitFor(() => expect(rosterParams().length).toBeGreaterThan(0));
    expect(rosterParams().every((params) => params.position_id !== 'position-deleted')).toBe(true);
    expect(latestRosterParams().position_id).toBeUndefined();
    expect(screen.getByRole('combobox', { name: 'Должность' })).toHaveValue('all');
    expect(new URLSearchParams(window.location.search).get('staff_position')).toBeNull();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('never presents a stale count and explains an empty query with a working reset', async () => {
    let resolveEmpty: ((value: unknown) => void) | undefined;
    installRosterReads((params) => {
      if (params.q === 'нет') {
        return new Promise((resolve) => { resolveEmpty = resolve; });
      }
      return { items: [pageEmployee], total: 41, page: params.page || 1, page_size: 20 };
    });
    render(<StaffWorkspace {...defaultProps} />);
    expect(await screen.findByText('Найдено: 41')).toBeInTheDocument();

    fireEvent.change(await openPeopleWorkspace(), { target: { value: 'нет' } });
    fireEvent.click(screen.getByRole('button', { name: 'Найти' }));

    expect(await screen.findByRole('status')).toHaveTextContent(/Загрузка сотрудников/i);
    expect(screen.queryByText('Найдено: 41')).not.toBeInTheDocument();
    await act(async () => {
      resolveEmpty?.({ items: [], total: 0, page: 1, page_size: 20 });
    });

    const empty = await screen.findByText(/«нет»/i);
    expect(empty).toHaveTextContent(/вся компания/i);
    expect(screen.getAllByRole('button', { name: 'Сбросить фильтры' })).toHaveLength(1);
    const emptyRegion = empty.closest('div') || empty.parentElement;
    fireEvent.click(within(emptyRegion as HTMLElement).getByRole('button', { name: 'Сбросить фильтры' }));

    await waitFor(() => expect(screen.getByRole('searchbox', { name: /поиск/i })).toHaveValue(''));
    expect(document.activeElement).toBe(screen.getByRole('searchbox', { name: /поиск/i }));
    expect(new URLSearchParams(window.location.search).get('staff_q')).toBeNull();
    expect(await screen.findByText(pageEmployee.full_name)).toBeInTheDocument();
    expect(postMock).not.toHaveBeenCalled();
  });
});
