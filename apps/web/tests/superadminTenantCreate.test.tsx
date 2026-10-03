import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SuperAdminTenants from '@/app/admin/super/tenants/page';
import { useAuthStore } from '@/store/authStore';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock('@/lib/api', () => ({ api: apiMock }));

describe('superadmin tenant creation prerequisites', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockResolvedValue({ data: { tenants: [] } });
    useAuthStore.setState({
      accessToken: 'superadmin-token',
      user: {
        user_id: 'superadmin-1', tenant_id: null, tenant: null,
        telegram_id: '', role: 'superadmin', roles: ['superadmin'],
        full_name: 'Platform Admin', email: 'admin@example.test',
      },
    });
  });

  it('keeps blank step one from advancing or posting, then advances valid input without posting', async () => {
    render(<SuperAdminTenants />);
    fireEvent.click(await screen.findByRole('button', { name: /Новый тенант/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Создать тенанта' });

    expect(within(dialog).getByLabelText('Название компании')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Slug')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Далее' }));
    expect(within(dialog).getByLabelText('Название компании')).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText('Название компании'), { target: { value: '   ' } });
    fireEvent.change(within(dialog).getByLabelText('Slug'), { target: { value: 'valid-slug' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Далее' }));
    expect(within(dialog).getByLabelText('Название компании')).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText('Название компании'), { target: { value: 'Acme' } });
    fireEvent.change(within(dialog).getByLabelText('Slug'), { target: { value: 'a' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Далее' }));
    expect(within(dialog).getByLabelText('Название компании')).toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText('Название компании'), { target: { value: 'Acme' } });
    fireEvent.change(within(dialog).getByLabelText('Slug'), { target: { value: 'acme' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Далее' }));
    await waitFor(() => expect(within(dialog).getByText(/Первый администратор/)).toBeInTheDocument());
    expect(apiMock.post).not.toHaveBeenCalled();
  });
});
