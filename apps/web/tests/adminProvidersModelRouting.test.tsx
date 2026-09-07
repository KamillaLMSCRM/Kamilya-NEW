import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AdminProvidersPage from '@/app/admin/providers/page';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';

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
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test/api');
    useLanguageStore.setState({ lang: 'ru' });
    useAuthStore.setState({
      accessToken: 'superadmin-token',
      user: {
        user_id: 'superadmin-1', tenant_id: null, tenant: null,
        telegram_id: '', role: 'superadmin', roles: ['superadmin'],
        full_name: 'Platform Admin', email: 'admin@example.test',
      },
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/admin/provider-keys')) {
        return new Response(JSON.stringify({ providers: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/admin/model-routing') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        return new Response(JSON.stringify({
          ...routing,
          revision: 8,
          models: routing.models.map((model) => ({
            ...model,
            position: body.ordered_model_ids.indexOf(model.id) + 1,
          })),
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.endsWith('/admin/model-routing')) {
        return new Response(JSON.stringify(routing), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('keeps DeepSeek first and persists an accessible fallback reorder', async () => {
    render(<AdminProvidersPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Очередность моделей' }));

    const dialog = await screen.findByRole('dialog', { name: 'Очередность моделей генерации' });
    expect(within(dialog).getByText('DeepSeek')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Поднять DeepSeek' })).toBeDisabled();
    expect(within(dialog).getAllByRole('button', { name: 'Отключить' })).toHaveLength(2);

    fireEvent.click(within(dialog).getByRole('button', { name: 'Поднять GLM 5.3 Flash' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'https://api.example.test/api/v1/admin/model-routing',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({
            revision: 7,
            ordered_model_ids: ['deepseek', 'glm53_flash', 'qwen38_flash_next'],
          }),
        }),
      );
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
