import { afterEach, describe, expect, it, vi } from 'vitest';

import { testTelegram } from '@/features/integrations/api';

describe('integrations API errors', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('surfaces the backend error-envelope message for a failed Telegram test', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: 'validation_error',
            message: 'Input validation failed',
            details: [],
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    await expect(testTelegram('test-token')).rejects.toThrow('Input validation failed');
  });
});
