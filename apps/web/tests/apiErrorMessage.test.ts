import { describe, expect, it } from 'vitest';
import { apiErrorMessage } from '@/lib/apiErrorMessage';

describe('bounded API error display', () => {
  it('keeps string detail and provider error bodies', () => {
    expect(apiErrorMessage({ response: { status: 409, data: { detail: 'revision conflict' } } }, 'fallback')).toBe('revision conflict');
    expect(apiErrorMessage({ response: { status: 502, data: { error: 'provider unavailable' } } }, 'fallback')).toBe('provider unavailable');
  });
  it('shows structured validation messages without request input or configuration', () => {
    const message = apiErrorMessage({
      response: { status: 422, data: { detail: [
        { msg: 'Field required', input: 'synthetic-secret' },
        { msg: 'Invalid value', ctx: { secret: 'synthetic-secret' } },
      ] } },
      config: { headers: { Authorization: 'synthetic-secret' } },
    }, 'fallback');
    expect(message).toBe('Field required; Invalid value');
    expect(message).not.toContain('synthetic-secret');
  });
  it('preserves HTTP status or caller fallback for unusable bodies', () => {
    expect(apiErrorMessage({ response: { status: 422, data: { detail: [null, {}] } } }, 'fallback')).toBe('HTTP 422');
    expect(apiErrorMessage(null, 'fallback')).toBe('fallback');
  });
});
