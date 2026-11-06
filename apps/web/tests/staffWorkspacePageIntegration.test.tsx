import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

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
  usePathname: () => '/staff',
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const getMock = vi.mocked(api.get);
let AdminStaffPage: (props: Record<string, never>) => JSX.Element;
let StaffRoutePage: (props: Record<string, never>) => JSX.Element;

const overview = {
  units: [{
    id: 'unit-root',
    name: 'Головной офис',
    parent_id: null,
    unit_type: 'organization',
    is_active: true,
    is_head_office: true,
    head_user_id: null,
    breadcrumb: ['Головной офис'],
    direct_count: 1,
    subtree_count: 1,
    hr_managed: false,
  }],
  positions: [],
  total: 1,
  unplaced_count: 0,
};

const roster = {
  items: [{
    id: 'employee-1',
    full_name: 'Айгерим Садыкова',
    personnel_number: 'EMP-001',
    is_active: true,
    organization_unit_id: 'unit-root',
    effective_unit_id: 'unit-root',
    placement_source: 'explicit',
    position_id: null,
    position_name: null,
    hr_managed: false,
  }],
  total: 1,
  page: 1,
  page_size: 20,
};

beforeAll(async () => {
  vi.stubEnv('NEXT_PUBLIC_STAFF_STRUCTURE_V3_ENABLED', 'true');
  const [adminStaff, staffRoute] = await Promise.all([
    import('@/app/admin/staff/page'),
    import('@/app/staff/page'),
  ]);
  AdminStaffPage = adminStaff.default;
  StaffRoutePage = staffRoute.default;
});

beforeEach(() => {
  useAuthStore.setState({
    accessToken: 'synthetic-test-token',
    user: {
      user_id: 'methodologist-1',
      tenant_id: 'tenant-test',
      tenant: { id: 'tenant-test', name: 'Synthetic tenant' },
      role: 'methodologist',
      roles: ['methodologist'],
      full_name: 'Synthetic Methodologist',
      email: 'methodologist@example.test',
    } as never,
  });
  window.history.replaceState({}, '', '/staff');
  window.sessionStorage.clear();
  vi.clearAllMocks();
  getMock.mockImplementation(async (url: string) => {
    if (url === '/v1/admin/staff/import/mappings') return { data: [] } as never;
    if (url === '/v1/organization-units/workspace') return { data: overview } as never;
    if (url === '/v1/organization-units/employees') return { data: roster } as never;
    throw new Error(`Unexpected staff page GET ${url}`);
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

afterAll(() => vi.unstubAllEnvs());

describe('staff workspace page integration', () => {
  it('archives through a cancellable page dialog, without a native confirm or an implicit write', async () => {
    let currentOverview = { ...overview, units: [{ ...overview.units[0], name: 'QA Архив', breadcrumb: ['QA Архив'], is_head_office: false }] };
    getMock.mockImplementation(async (url: string) => {
      if (url === '/v1/admin/staff/import/mappings') return { data: [] } as never;
      if (url === '/v1/organization-units/workspace') return { data: currentOverview } as never;
      if (url === '/v1/organization-units/employees') return { data: roster } as never;
      throw new Error(`Unexpected GET ${url}`);
    });
    const nativeConfirm = vi.spyOn(window, 'confirm').mockImplementation(() => { throw new Error('Native confirm forbidden'); });
    const post = vi.mocked(api.post);
    post.mockImplementation(async () => {
      currentOverview = { ...currentOverview, units: [{ ...currentOverview.units[0], is_active: false }] };
      return { data: {} } as never;
    });
    render(<AdminStaffPage />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Структура' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть подразделение: QA Архив' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Архивировать подразделение' }));
    let dialog = await screen.findByRole('dialog', { name: 'Архивировать подразделение' });
    expect(within(dialog).getByText(/QA Архив/)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(screen.queryByRole('dialog', { name: 'Архивировать подразделение' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать подразделение' }));
    dialog = await screen.findByRole('dialog', { name: 'Архивировать подразделение' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить архивирование' }));
    await waitFor(() => expect(post).toHaveBeenCalledExactlyOnceWith('/v1/organization-units/unit-root/archive', {
      reason: 'Архивировано методистом через раздел структуры',
    }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Архивировать подразделение' })).not.toBeInTheDocument());
    expect((await screen.findAllByText('Архивное подразделение')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Архивировать подразделение' })).not.toBeInTheDocument();
    expect(nativeConfirm).not.toHaveBeenCalled();
  });
  it('loads the real workspace for a methodologist without legacy structure or bulk owner reads', async () => {
    render(<AdminStaffPage />);

    fireEvent.click(await screen.findByRole('tab', { name: 'Структура' }));
    expect(await screen.findByRole('button', { name: 'Открыть подразделение: Головной офис' })).toBeInTheDocument();
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith(
        '/v1/organization-units/workspace',
        expect.anything(),
      );
      expect(getMock).toHaveBeenCalledWith(
        '/v1/organization-units/employees',
        expect.objectContaining({
          params: expect.objectContaining({ page: 1, page_size: 20 }),
        }),
      );
    });
    expect(getMock).not.toHaveBeenCalledWith('/v1/organization-units/tree');
    expect(getMock).not.toHaveBeenCalledWith('/v1/users?per_page=500&role=methodologist&is_active=true');
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1, name: 'Сотрудники и структура' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: 'Сотрудники и структура' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Добавить сотрудника/ })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Добавить подразделение' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Импорт/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Структура/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('creates a branch at the top level and a team under the chosen real parent', async () => {
    let current: Omit<typeof overview, 'units'> & { units: (Omit<(typeof overview.units)[number], 'parent_id'> & { parent_id: string | null })[] } = overview;
    const post = vi.mocked(api.post);
    getMock.mockImplementation(async (url: string) => {
      if (url === '/v1/organization-units/workspace') return { data: current } as never;
      if (url === '/v1/organization-units/employees') return { data: roster } as never;
      return { data: [] } as never;
    });
    post.mockImplementation(async (_url, body) => {
      const change = body as { name: string; unit_type: string; parent_id: string | null };
      const id = change.parent_id ? 'team-created' : 'branch-created';
      const parent = current.units.find((unit) => unit.id === change.parent_id);
      const unit = { ...overview.units[0], id, name: change.name, unit_type: change.unit_type,
        parent_id: change.parent_id, is_head_office: false, breadcrumb: [...(parent?.breadcrumb ?? []), change.name] };
      current = { ...current, units: [...current.units, unit] };
      return { data: { id } } as never;
    });
    render(<AdminStaffPage />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Структура' }));
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подразделение' }));
    let dialog = within(screen.getByRole('dialog'));
    fireEvent.change(dialog.getByRole('textbox'), { target: { value: 'Филиал Шымкент' } });
    fireEvent.click(dialog.getByRole('button', { name: /Создать/ }));
    await waitFor(() => expect(window.location.search).toContain('staff_unit=branch-created'));
    expect(post).toHaveBeenCalledWith('/v1/organization-units', { name: 'Филиал Шымкент', unit_type: 'branch', parent_id: null });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить сюда' }));
    dialog = within(screen.getByRole('dialog'));
    fireEvent.change(dialog.getByRole('textbox'), { target: { value: 'Команда' } });
    fireEvent.change(dialog.getAllByRole('combobox')[0], { target: { value: 'team' } });
    expect(dialog.getAllByRole('combobox')[1]).toHaveValue('branch-created');
    fireEvent.click(dialog.getByRole('button', { name: /Создать/ }));
    await waitFor(() => expect(window.location.search).toContain('staff_unit=team-created'));
    expect(post).toHaveBeenCalledWith('/v1/organization-units', { name: 'Команда', unit_type: 'team', parent_id: 'branch-created' });
  });

  it('preserves the canonical page header and manual employee action on the import tab', async () => {
    window.history.replaceState({}, '', '/staff?tab=import');

    render(<AdminStaffPage />);

    expect(await screen.findByRole('tab', { name: /Импорт/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('button', { name: /Добавить сотрудника/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Добавить подразделение' })).not.toBeInTheDocument();
  });

  it('keeps /staff as the canonical re-export of the actual admin staff page', () => {
    expect(StaffRoutePage).toBe(AdminStaffPage);
  });

  it.each(['admin', 'student'] as const)('%s receives no staff workspace or staff data reads', async (role) => {
    window.sessionStorage.setItem('kamilya-adaptive-import-session-id', 'prior-methodologist-session');
    useAuthStore.setState({
      user: {
        user_id: `${role}-1`,
        tenant_id: 'tenant-test',
        role,
        roles: [role],
      } as never,
    });

    render(<AdminStaffPage />);

    expect(await screen.findByRole('heading', { name: /доступ к разделу закрыт/i })).toBeInTheDocument();
    await waitFor(() => expect(getMock).not.toHaveBeenCalled());
    expect(getMock).not.toHaveBeenCalledWith('/v1/organization-units/workspace', expect.anything());
    expect(getMock).not.toHaveBeenCalledWith('/v1/organization-units/employees', expect.anything());
    expect(getMock).not.toHaveBeenCalledWith('/v1/organization-units/tree');
    expect(getMock).not.toHaveBeenCalledWith('/v1/users?per_page=500&role=methodologist&is_active=true');
  });
});
