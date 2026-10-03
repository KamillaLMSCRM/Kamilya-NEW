import { createEvent, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
    const nextButton = within(dialog).getByRole('button', { name: 'Далее' });
    const click = createEvent.click(nextButton);
    fireEvent(nextButton, click);
    expect(click.defaultPrevented).toBe(true);
    await waitFor(() => expect(within(dialog).getByText(/Первый администратор/)).toBeInTheDocument());
    expect(within(dialog).getByRole('button', { name: 'Создать тенанта' })).not.toBe(nextButton);
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('still posts exactly once after an explicit valid final submit', async () => {
    apiMock.post.mockResolvedValue({ data: {
      tenant: { id: 'tenant-synthetic', name: 'Acme', slug: 'acme' },
      first_admin: null,
      invite_url: null,
    } });
    render(<SuperAdminTenants />);
    fireEvent.click(await screen.findByRole('button', { name: /Новый тенант/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Создать тенанта' });
    fireEvent.change(within(dialog).getByLabelText('Название компании'), { target: { value: 'Acme' } });
    fireEvent.change(within(dialog).getByLabelText('Slug'), { target: { value: 'acme' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Далее' }));
    expect(apiMock.post).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText('Email'), { target: { value: 'admin@example.test' } });
    fireEvent.change(within(dialog).getByLabelText('Имя'), { target: { value: 'Test' } });
    fireEvent.change(within(dialog).getByLabelText('Фамилия'), { target: { value: 'Admin' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Создать тенанта' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
    expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/super/tenants', expect.objectContaining({
      name: 'Acme', slug: 'acme',
      first_admin: expect.objectContaining({ email: 'admin@example.test', first_name: 'Test', last_name: 'Admin' }),
    }));
  });
});
