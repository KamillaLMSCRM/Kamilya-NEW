import { render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SuperAdminLanding from '@/app/admin/super/page';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));

const tenant = { id: 'tenant-1', name: 'Acme', slug: 'acme', status: 'active', plan: 'trial', stats: null };

describe('superadmin landing onboarding state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      accessToken: 'superadmin-token',
      user: { user_id: 'superadmin-1', tenant_id: null, tenant: null, telegram_id: '', role: 'superadmin', roles: ['superadmin'], full_name: 'Platform Admin', email: 'admin@example.test' },
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('does not flash first-tenant onboarding while loading or after tenants load', async () => {
    let resolve: () => void = () => {};
    apiMock.get.mockImplementation(() => new Promise<{ data: { tenants: typeof tenant[] } }>((done) => {
      resolve = () => done({ data: { tenants: [tenant] } });
    }));

    render(<SuperAdminLanding />);
    expect(screen.queryByText('Запуск первого тенанта')).not.toBeInTheDocument();

    resolve();
    await waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());
    expect(screen.queryByText('Запуск первого тенанта')).not.toBeInTheDocument();
  });

  it('shows first-tenant onboarding only after a successful empty response', async () => {
    apiMock.get.mockResolvedValue({ data: { tenants: [] } });

    render(<SuperAdminLanding />);
    expect(await screen.findByText('Запуск первого тенанта')).toBeInTheDocument();
  });

  it('does not present a failed request as an empty platform', async () => {
    apiMock.get.mockRejectedValue(new Error('HTTP 503'));

    render(<SuperAdminLanding />);
    await screen.findByText('0');
    expect(screen.queryByText('Запуск первого тенанта')).not.toBeInTheDocument();
  });

  it('keeps tenant detail controls associated with their visible labels', () => {
    const page = readFileSync(resolve(process.cwd(), 'src/app/admin/super/tenants/[id]/page.tsx'), 'utf8');
    for (const id of ['tenant-name', 'tenant-slug', 'tenant-plan', 'tenant-status', 'tenant-trial-ends', 'tenant-paid-until', 'tenant-max-users', 'tenant-max-courses', 'tenant-notes']) {
      expect(page).toContain(`htmlFor="${id}"`);
      expect(page).toContain(`id="${id}"`);
    }
    expect(page).toContain('id="tenant-impersonate-role"');
    expect(page).toContain("aria-label={t('superadmin.tenants.impersonate.label')}");
  });
});
