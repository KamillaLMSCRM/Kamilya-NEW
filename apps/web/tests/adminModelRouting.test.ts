import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));

import {
  getGenerationModelRouting,
  ModelRoutingRequestError,
  saveGenerationModelRouting,
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
});
