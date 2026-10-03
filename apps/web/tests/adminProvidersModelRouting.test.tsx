import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AdminProvidersPage from '@/app/admin/providers/page';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  put: vi.fn(),
}));
vi.mock('@/lib/api', () => ({ api: apiMock }));

const routing = {
  revision: 7,
  updated_at: '2026-09-07T10:00:00Z',
  models: [
    {
      id: 'deepseek', provider: 'deepseek', display_name: 'DeepSeek',
      model: 'deepseek-v4-flash', is_enabled: true, position: 1,
      is_required: true, is_configured: true,
    },
    {
      id: 'qwen38_flash_next', provider: 'custom:qwen38-flash-next',
      display_name: 'Qwen 3.8 Flash Next', model: 'qwen3.8-flash-next',
      is_enabled: true, position: 2, is_required: false, is_configured: true,
    },
    {
      id: 'glm53_flash', provider: 'glm53-flash-asus',
      display_name: 'GLM 5.3 Flash', model: 'GLM-5.3-Flash',
      is_enabled: true, position: 3, is_required: false, is_configured: true,
    },
  ],
};

describe('superadmin generation model routing modal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === '/v1/admin/provider-keys') return { data: { providers: [] } };
      if (url === '/v1/admin/model-routing') return { data: routing };
      throw new Error(`Unexpected request: ${url}`);
    });
    apiMock.put.mockImplementation(async (_url: string, body: { ordered_model_ids: string[] }) => ({
      data: {
        ...routing,
        revision: 8,
        models: routing.models.map((model) => ({
          ...model,
          position: body.ordered_model_ids.indexOf(model.id) + 1,
        })),
      },
    }));
    useLanguageStore.setState({ lang: 'ru' });
    useAuthStore.setState({
      accessToken: 'superadmin-token',
      user: {
        user_id: 'superadmin-1', tenant_id: null, tenant: null,
        telegram_id: '', role: 'superadmin', roles: ['superadmin'],
        full_name: 'Platform Admin', email: 'admin@example.test',
      },
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('keeps DeepSeek first and persists an accessible fallback reorder', async () => {
    render(<AdminProvidersPage />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/admin/provider-keys'));
    fireEvent.click(await screen.findByRole('button', { name: 'Очередность моделей' }));

    const dialog = await screen.findByRole('dialog', { name: 'Очередность моделей генерации' });
    expect(within(dialog).getByText('DeepSeek')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Поднять DeepSeek' })).toBeDisabled();
    expect(within(dialog).getAllByRole('button', { name: 'Отключить' })).toHaveLength(2);

    fireEvent.click(within(dialog).getByRole('button', { name: 'Поднять GLM 5.3 Flash' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith(
      '/v1/admin/model-routing',
      { revision: 7, ordered_model_ids: ['deepseek', 'glm53_flash', 'qwen38_flash_next'] },
    ));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('associates add-key labels and keeps save disabled without a key', async () => {
    render(<AdminProvidersPage />);

    fireEvent.click(await screen.findByRole('button', { name: /Добавить ключ/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый API-ключ' });

    expect(within(dialog).getByLabelText('Провайдер')).toHaveAttribute(
      'id',
      'provider-key-provider',
    );
    expect(within(dialog).getByLabelText('API-ключ')).toHaveAttribute(
      'id',
      'provider-key-api-key',
    );
    expect(within(dialog).getByLabelText('Метка (опционально)')).toHaveAttribute(
      'id',
      'provider-key-label',
    );
    expect(within(dialog).getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    expect(apiMock.get).toHaveBeenCalledTimes(1);
  });

  it('closes the add-key dialog without submitting', async () => {
    render(<AdminProvidersPage />);

    fireEvent.click(await screen.findByRole('button', { name: /Добавить ключ/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый API-ключ' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(apiMock.get).toHaveBeenCalledTimes(1);
  });
});
