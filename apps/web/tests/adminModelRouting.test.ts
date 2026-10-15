import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));

import {
  getGenerationModelRouting,
  ModelRoutingRequestError,
  saveGenerationModelRouting,
  checkChatGPTReadiness,
  buildChatGPTReserveOrder,
} from '@/lib/adminModelRouting';

describe('canonical model-routing transport errors', () => {
  beforeEach(() => vi.clearAllMocks());

  it('preserves 409 conflict detail and status', async () => {
    apiMock.put.mockRejectedValue({ response: { status: 409, data: { detail: 'revision conflict' } } });
    await expect(saveGenerationModelRouting(7, ['deepseek'])).rejects.toMatchObject({
      name: 'Error', message: 'revision conflict', status: 409,
    });
    try {
      await saveGenerationModelRouting(7, ['deepseek']);
    } catch (error) {
      expect(error).toBeInstanceOf(ModelRoutingRequestError);
    }
  });

  it('preserves non-success load status', async () => {
    apiMock.get.mockRejectedValue({ response: { status: 422, data: { detail: 'invalid route' } } });
    await expect(getGenerationModelRouting()).rejects.toMatchObject({
      message: 'invalid route', status: 422,
    });
  });

  it('preserves structured validation messages without exposing inputs', async () => {
    apiMock.put.mockRejectedValue({ response: { status: 422, data: {
      detail: [{ msg: 'Revision required', input: 'synthetic-secret' }],
    } } });
    await expect(saveGenerationModelRouting(7, ['deepseek'])).rejects.toMatchObject({
      message: 'Revision required', status: 422,
    });
  });

  it('checks readiness through the explicit readiness endpoint without inference inputs', async () => {
    apiMock.post.mockResolvedValue({
      data: { ready: false, reason: 'authorization_required', checked_at: '2026-10-15T10:00:00Z' },
    });
    await expect(checkChatGPTReadiness()).resolves.toEqual({
      ready: false, reason: 'authorization_required', checked_at: '2026-10-15T10:00:00Z',
    });
    expect(apiMock.post).toHaveBeenCalledWith('/v1/admin/model-routing/chatgpt-readiness');
  });

  it('preserves a closed readiness reason on a 409 so callers do not mislabel it as revision conflict', async () => {
    apiMock.post.mockRejectedValue({ response: { status: 409, data: { detail: 'authorization_required' } } });
    await expect(checkChatGPTReadiness()).rejects.toMatchObject({ status: 409, reason: 'authorization_required' });
  });

  it('does not classify unrelated primary configuration errors as reserve errors', async () => {
    apiMock.put.mockRejectedValue({ response: { status: 409, data: { detail: 'generation_model_routing_deepseek_not_configured' } } });
    await expect(saveGenerationModelRouting(7, ['deepseek'])).rejects.toMatchObject({ status: 409, reason: undefined });
  });

  it('builds activation from the authoritative server snapshot, ignoring a cancelled UI draft', () => {
    const routing = {
      revision: 8,
      updated_at: 'now',
      models: [
        { id: 'deepseek', provider: 'deepseek', display_name: 'DeepSeek', model: 'x', is_enabled: true, position: 0, is_required: true, is_configured: true },
        { id: 'voyage', provider: 'voyage', display_name: 'Voyage', model: 'x', is_enabled: true, position: 1, is_required: false, is_configured: true },
        { id: 'chatgpt_reserve', provider: 'chatgpt', display_name: 'Reserve', model: 'x', is_enabled: false, position: null, is_required: false, is_configured: true },
      ],
    };
    expect(buildChatGPTReserveOrder(routing, true)).toEqual(['deepseek', 'chatgpt_reserve', 'voyage']);
    expect(buildChatGPTReserveOrder(routing, false)).toEqual(['deepseek', 'voyage']);
  });
});
