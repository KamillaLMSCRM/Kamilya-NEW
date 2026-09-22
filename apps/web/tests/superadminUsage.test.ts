import { describe, expect, it } from 'vitest';

import { formatUsageCounter } from '@/features/superadmin/usage';

describe('superadmin usage presentation', () => {
  it('shows the real non-default limit returned by the server', () => {
    expect(formatUsageCounter(3, 7, 'без лимита')).toBe('3 / 7');
  });

  it('states unlimited usage instead of inventing a denominator', () => {
    expect(formatUsageCounter(3, null, 'без лимита')).toBe('3 / без лимита');
    expect(formatUsageCounter(undefined, undefined, 'unlimited')).toBe('0 / unlimited');
  });
});
