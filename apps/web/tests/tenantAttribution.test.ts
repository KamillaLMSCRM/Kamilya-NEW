import { describe, expect, it } from 'vitest';

import { extractTenantAttribution } from '@/lib/tenantAttribution';

describe('extractTenantAttribution', () => {
  it('preserves campaign and landing source across the trial-registration boundary', () => {
    expect(
      extractTenantAttribution(
        '?utm_source=google&utm_medium=cpc&utm_campaign=kz_lms&utm_content=hero&utm_term=lms%20%D1%81%D0%B8%D1%81%D1%82%D0%B5%D0%BC%D0%B0&referrer=https%3A%2F%2Fwww.kml.kz%2Fru',
        'https://ignored.example',
      ),
    ).toEqual({
      utm_source: 'google',
      utm_medium: 'cpc',
      utm_campaign: 'kz_lms',
      utm_content: 'hero',
      utm_term: 'lms система',
      referrer: 'https://www.kml.kz/ru',
    });
  });

  it('falls back to the browser referrer and enforces backend length limits', () => {
    const result = extractTenantAttribution(`?utm_campaign=${'x'.repeat(150)}`, 'https://www.kml.kz/kk');
    expect(result.utm_campaign).toHaveLength(100);
    expect(result.referrer).toBe('https://www.kml.kz/kk');
  });
});
