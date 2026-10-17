import { cleanup, render, screen, waitFor } from '@testing-library/react';
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
});

afterAll(() => vi.unstubAllEnvs());

describe('staff workspace page integration', () => {
  it('loads the real workspace for a methodologist without legacy structure or bulk owner reads', async () => {
    render(<AdminStaffPage />);

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
