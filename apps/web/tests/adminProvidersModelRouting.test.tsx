import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  function reserveScenario(enabled = false) {
    let current = {
      ...routing,
      models: [...routing.models, {
        id: 'chatgpt_reserve', provider: 'chatgpt-reserve', display_name: 'ChatGPT Luna (manual reserve)',
        model: 'gpt-5.6-luna', is_enabled: enabled, position: enabled ? 4 : null,
        is_required: false, is_configured: true,
      }],
    };
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === '/v1/admin/provider-keys') return { data: { providers: [] } };
      if (url === '/v1/admin/model-routing') return { data: current };
      throw new Error('Unexpected request');
    });
    apiMock.post.mockResolvedValue({ data: { ready: true, reason: 'ready', checked_at: '2026-10-15T06:00:00Z' } });
    apiMock.put.mockImplementation(async (_url: string, body: { ordered_model_ids: string[] }) => {
      current = { ...current, revision: current.revision + 1, models: current.models.map((model) => ({
        ...model, is_enabled: body.ordered_model_ids.includes(model.id),
        position: body.ordered_model_ids.includes(model.id) ? body.ordered_model_ids.indexOf(model.id) + 1 : null,
      })) };
      return { data: current };
    });
  }

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
    vi.unstubAllGlobals();
  });

  it('opening the reserve only reads state and never probes or enables', async () => {
    reserveScenario();
    render(<AdminProvidersPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Резерв ChatGPT' }));
    const dialog = await screen.findByRole('dialog', { name: 'Резерв ChatGPT' });
    expect(await within(dialog).findByText('Отключён')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Включить резерв' })).toBeDisabled();
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it('requires explicit readiness and confirmation without carrying a canceled reorder', async () => {
    reserveScenario();
    const confirm = vi.fn(() => false);
    vi.stubGlobal('confirm', confirm);
    render(<AdminProvidersPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Очередность моделей' }));
    const routingDialog = await screen.findByRole('dialog', { name: 'Очередность моделей генерации' });
    fireEvent.click(await within(routingDialog).findByRole('button', { name: 'Поднять GLM 5.3 Flash' }));
    fireEvent.click(within(routingDialog).getByRole('button', { name: 'Отмена' }));
    fireEvent.click(screen.getByRole('button', { name: 'Резерв ChatGPT' }));
    const dialog = await screen.findByRole('dialog', { name: 'Резерв ChatGPT' });
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Проверить готовность' }));
    const enable = within(dialog).getByRole('button', { name: 'Включить резерв' });
    await waitFor(() => expect(enable).toBeEnabled());
    fireEvent.click(enable);
    expect(apiMock.put).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(enable);
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/v1/admin/model-routing', {
      revision: 7, ordered_model_ids: ['deepseek', 'chatgpt_reserve', 'qwen38_flash_next', 'glm53_flash'],
    }));
    expect(await within(dialog).findByText('Включён')).toBeInTheDocument();
    expect(apiMock.post).toHaveBeenCalledTimes(1);
  });

  it('disables through the real page handlers without probing', async () => {
    reserveScenario(true);
    render(<AdminProvidersPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Резерв ChatGPT' }));
    const dialog = await screen.findByRole('dialog', { name: 'Резерв ChatGPT' });
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Отключить резерв' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/v1/admin/model-routing', {
      revision: 7, ordered_model_ids: ['deepseek', 'qwen38_flash_next', 'glm53_flash'],
    }));
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(await within(dialog).findByText('Отключён')).toBeInTheDocument();
  });

  it('a server activation refusal reloads state and clears old readiness', async () => {
    reserveScenario();
    vi.stubGlobal('confirm', vi.fn(() => true));
    apiMock.put.mockRejectedValue({ response: { status: 409, data: { detail: 'unavailable' } } });
    render(<AdminProvidersPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Резерв ChatGPT' }));
    const dialog = await screen.findByRole('dialog', { name: 'Резерв ChatGPT' });
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Проверить готовность' }));
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Включить резерв' })).toBeEnabled());
    fireEvent.click(within(dialog).getByRole('button', { name: 'Включить резерв' }));
    await waitFor(() => expect(apiMock.get.mock.calls.filter(([url]) => url === '/v1/admin/model-routing')).toHaveLength(2));
    expect(await within(dialog).findByText('Готовность ещё не проверялась.')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Включить резерв' })).toBeDisabled();
  });

  it('a late readiness response cannot repopulate status after disabling', async () => {
    reserveScenario(true);
    let resolveProbe!: (value: { data: { ready: boolean; reason: string; checked_at: string } }) => void;
    apiMock.post.mockReturnValue(new Promise((resolve) => { resolveProbe = resolve; }));
    render(<AdminProvidersPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Резерв ChatGPT' }));
    const dialog = await screen.findByRole('dialog', { name: 'Резерв ChatGPT' });
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Проверить готовность' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отключить резерв' }));
    expect(await within(dialog).findByText('Отключён')).toBeInTheDocument();
    await act(async () => resolveProbe({ data: { ready: true, reason: 'ready', checked_at: 'old-snapshot' } }));
    expect(within(dialog).getByText('Готовность ещё не проверялась.')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Включить резерв' })).toBeDisabled();
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
