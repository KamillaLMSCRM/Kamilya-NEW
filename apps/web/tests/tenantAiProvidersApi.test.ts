import { afterEach, describe, expect, it, vi } from 'vitest';
import { saveTenantAiSetting } from '@/lib/tenantAiProviders';

afterEach(() => vi.unstubAllGlobals());

describe('Tenant AI transport secrecy', () => {
  it('never includes a rejected secret-bearing response in thrown error', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ input: 'synthetic-key-do-not-echo' }] }), { status: 422 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(saveTenantAiSetting('token', 'generation', { provider: 'openrouter', model: 'openrouter/free', api_key: 'synthetic-key-do-not-echo', enabled: true, free_only: true, output_dimensions: null }, new AbortController().signal)).rejects.toThrow('tenant_ai_request_422');
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/v1\/admin\/ai-providers\/generation$/);
    expect(url).not.toContain('synthetic-key');
    expect(options.method).toBe('PUT');
    expect(options.cache).toBe('no-store');
  });
});
