import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AdminStaffPage from '@/app/admin/staff/page';
import {
  flattenOrganizationUnits,
  mergeUniqueOrganizationUnitRoots,
  type OrganizationUnitNode,
} from '@/features/staff-structure/organizationStructure';
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
const patchMock = vi.mocked(api.patch);

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

const position = {
  id: 'position-sector-1',
  name: 'Инженер сектора',
  department: 'Сектор испытаний',
  department_slug: 'sector-1',
  department_id: 'sector-1',
  employee_count: 1,
  employees: [{ id: 'employee-sector-1', full_name: 'Мария Иванова', personnel_number: '102', is_active: true }],
};

const fourLevelRoot = {
    id: 'office-1',
    name: 'Центральный офис',
    slug: 'central-office',
    unit_type: 'organization',
    parent_id: null,
    is_head_office: true,
    employee_count: 0,
    position_count: 0,
    positions: [],
    children: [{
      id: 'management-1',
      name: 'Управление качества',
      slug: 'quality-management',
      unit_type: 'management',
      parent_id: 'office-1',
      employee_count: 0,
      positions: [],
      children: [{
        id: 'division-1',
        name: 'Департамент испытаний',
        slug: 'testing-division',
        unit_type: 'division',
        parent_id: 'management-1',
        employee_count: 0,
        positions: [],
        children: [{
          id: 'sector-1',
          name: 'Сектор испытаний',
          slug: 'testing-sector',
          unit_type: 'sector',
          parent_id: 'division-1',
          employee_count: 1,
          position_count: 1,
          positions: [position],
          children: [],
        }],
      }],
    }],
  };

const fourLevelTree = {
  roots: [fourLevelRoot],
  branches: [],
  legacy_roots: [],
  unassigned_legacy_positions: [],
  summary: { total_branches: 1, total_departments: 3, total_positions: 1, total_employees: 1 },
};

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'test-token', user });
  window.history.replaceState({}, '', '/');
  getMock.mockImplementation(async (url: string) => {
    if (url.includes('/import/mappings')) return { data: [] } as any;
    if (url === '/v1/departments') return { data: { departments: [] } } as any;
    if (url === '/v1/positions') return { data: [] } as any;
    if (url.includes('/organization-units/tree')) return { data: fourLevelTree } as any;
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockReset();
  patchMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('organization hierarchy v2 public UI', () => {
  it('keeps depth eight visible and excludes only deeper corrupt input', () => {
    const root: OrganizationUnitNode = {
      id: 'depth-0', name: 'Level 0', children: [], positions: [],
    };
    let current = root;
    for (let depth = 1; depth <= 9; depth += 1) {
      const child: OrganizationUnitNode = {
        id: `depth-${depth}`, name: `Level ${depth}`, children: [], positions: [],
      };
      current.children = [child];
      current = child;
    }

    expect(flattenOrganizationUnits([root]).map((item) => item.depth)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8,
    ]);
  });

  it('prunes compatibility descendants already present in the canonical tree', () => {
    const compatibilityRoot: OrganizationUnitNode = {
      id: 'legacy-parent',
      name: 'Legacy parent',
      children: [{
        ...fourLevelRoot.children[0],
        children: [],
      }],
      positions: [],
    };

    const merged = mergeUniqueOrganizationUnitRoots(
      [fourLevelRoot],
      [compatibilityRoot],
    );

    expect(merged).toHaveLength(2);
    expect(merged[1].children).toEqual([]);
    expect(flattenOrganizationUnits(merged).filter((node) => node.id === 'management-1')).toHaveLength(1);
  });
  it('renders a four-level tree and positions at the deepest node', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Структура/i }));

    const office = await screen.findByRole('button', { name: /Центральный офис/i });
    fireEvent.click(office);
    const management = await screen.findByRole('button', { name: /Управление качества/i });
    fireEvent.click(management);
    const division = await screen.findByRole('button', { name: /Департамент испытаний/i });
    fireEvent.click(division);
    const sector = await screen.findByRole('button', { name: /Сектор испытаний/i });
    fireEvent.click(sector);

    fireEvent.click(await screen.findByRole('button', { name: /Инженер сектора/i }));
    expect(screen.getByText('Мария Иванова')).toBeInTheDocument();
  });

  it('shows the complete local breadcrumb and explicit head-office badge', async () => {
    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Структура/i }));

    expect((await screen.findAllByText('Центральный офис')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('Центральный офис')).length).toBeGreaterThan(1);
    fireEvent.click(screen.getByRole('button', { name: /Центральный офис/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Управление качества/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Департамент испытаний/i }));
    expect(screen.getByText('Путь: Центральный офис → Управление качества → Департамент испытаний → Сектор испытаний')).toBeInTheDocument();
    expect(screen.getAllByText('Сектор').length).toBeGreaterThan(0);
  });

  it('previews a recursive move before saving the new parent', async () => {
    postMock.mockResolvedValueOnce({
      data: {
        affected_units: 3,
        affected_positions: 2,
        affected_employees: 5,
        resulting_depth: 0,
        subtree_height: 2,
      },
    } as any);
    patchMock.mockResolvedValueOnce({ data: { id: 'management-1' } } as any);

    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('tab', { name: /Структура/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Центральный офис/i }));
    const moveButtons = await screen.findAllByRole('button', { name: 'Переместить' });
    fireEvent.click(moveButtons[1]);

    const dialog = await screen.findByRole('dialog', { name: 'Редактирование подразделения' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: 'Родительское подразделение' }), {
      target: { value: '' },
    });

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/v1/organization-units/management-1/move-preview',
      { parent_id: null },
    ));
    expect(await within(dialog).findByText(/3 подраздел.*2 должн.*5 сотр/i)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(patchMock).toHaveBeenCalledWith(
      '/v1/organization-units/management-1',
      { name: 'Управление качества', parent_id: null },
    ));
  });

  it('offers every existing position before a unit is selected', async () => {
    getMock.mockImplementation(async (url: string) => {
      if (url.includes('/import/mappings')) return { data: [] } as any;
      if (url === '/v1/departments') return { data: { departments: [] } } as any;
      if (url === '/v1/positions') return { data: [
        { id: 'position-without-unit', name: 'Директор без подразделения', department: null, department_id: null },
        { id: 'position-with-unit', name: 'Инженер', department: 'Сектор испытаний', department_id: 'sector-1' },
      ] } as any;
      if (url.includes('/organization-units/tree')) return { data: fourLevelTree } as any;
      throw new Error(`unexpected GET ${url}`);
    });

    render(<AdminStaffPage />);
    fireEvent.click(screen.getByRole('button', { name: /Добавить сотрудника/i }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });
    const positionSelect = await within(dialog).findByRole('combobox', { name: /^Должность/ });

    expect(within(positionSelect).getByRole('option', { name: 'Директор без подразделения' })).toBeInTheDocument();
    expect(within(positionSelect).getByRole('option', { name: /Инженер/ })).toBeInTheDocument();
  });
});
