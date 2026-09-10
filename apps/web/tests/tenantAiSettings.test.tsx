import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Page from '@/app/admin/settings/ai/page';
import { useAuthStore } from '@/store/authStore';
import { canAccessRoute } from '@/lib/rolePolicy';
import * as api from '@/lib/tenantAiProviders';
import type { AuthUser } from '@/lib/auth';

vi.mock('@/lib/tenantAiProviders', () => ({ getTenantAiSettings: vi.fn(), saveTenantAiSetting: vi.fn(), removeTenantAiSetting: vi.fn() }));

const setting = { purpose: 'generation' as const, provider: 'openrouter' as const, model: 'openrouter/free', has_key: true, enabled: true, free_only: true, output_dimensions: null };
const syntheticUser = (overrides: Partial<AuthUser> = {}): AuthUser => ({
  user_id: 'synthetic-admin', tenant_id: 'synthetic-tenant', tenant: null,
  role: 'admin', roles: ['admin'], telegram_id: '', full_name: 'Synthetic Admin',
  email: null, ...overrides,
});

describe('Tenant AI settings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ accessToken: 'synthetic-token', user: syntheticUser() });
    vi.mocked(api.getTenantAiSettings).mockResolvedValue([setting]);
    vi.mocked(api.saveTenantAiSetting).mockResolvedValue();
  });

  it('reserves the route and data request for tenant admin', () => {
    expect(canAccessRoute('admin', '/admin/settings/ai')).toBe(true);
    expect(canAccessRoute('methodologist', '/admin/settings/ai')).toBe(false);
    expect(canAccessRoute('student', '/admin/settings/ai')).toBe(false);
    useAuthStore.setState({ user: syntheticUser({ user_id: 'student', role: 'student', roles: ['student'] }) });
    render(<Page />);
    expect(screen.getByRole('alert')).toHaveTextContent('только администратору');
    expect(api.getTenantAiSettings).not.toHaveBeenCalled();
  });

  it('reads saved settings without displaying or resubmitting the stored key', async () => {
    render(<Page />);
    const heading = await screen.findByRole('heading', { name: 'Генерация курса и теста' });
    const form = within(heading.parentElement!);
    expect(form.getByLabelText('API-ключ')).toHaveValue('');
    fireEvent.click(form.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(api.saveTenantAiSetting).toHaveBeenCalled());
    const payload = vi.mocked(api.saveTenantAiSetting).mock.calls[0][2];
    expect(payload).not.toHaveProperty('api_key');
    expect(payload.free_only).toBe(true);
    expect(await form.findByRole('status')).toHaveTextContent('прочитаны с сервера');
  });

  it('requires a new key when changing provider and rejects a paid free-mode model', async () => {
    render(<Page />);
    const heading = await screen.findByRole('heading', { name: 'Генерация курса и теста' });
    const form = within(heading.parentElement!);
    fireEvent.change(form.getByLabelText('Идентификатор модели'), { target: { value: 'paid/model' } });
    expect(form.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    fireEvent.change(form.getByLabelText('Провайдер'), { target: { value: 'deepseek' } });
    fireEvent.change(form.getByLabelText('Идентификатор модели'), { target: { value: 'deepseek-test' } });
    expect(form.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
  });

  it('does not render an empty editable form when authoritative load fails', async () => {
    vi.mocked(api.getTenantAiSettings).mockRejectedValue(new Error('sensitive synthetic body'));
    render(<Page />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось прочитать');
    expect(screen.queryByText('sensitive synthetic body')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('API-ключ')).not.toBeInTheDocument();
  });

  it('clears typed keys and reloads settings on tenant switch', async () => {
    render(<Page />);
    const inputs = await screen.findAllByLabelText('API-ключ');
    fireEvent.change(inputs[0], { target: { value: 'synthetic-private-key' } });
    useAuthStore.setState({ user: syntheticUser({ user_id: 'second-admin', tenant_id: 'second-tenant' }) });
    await waitFor(() => expect(api.getTenantAiSettings).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getAllByLabelText('API-ключ')[0]).toHaveValue(''));
  });
});
