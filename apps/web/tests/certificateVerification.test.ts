import { describe, expect, it } from 'vitest';
import {
  formatVerificationDate,
  getCertificateVerificationPath,
  normalizeCertificateNumber,
} from '@/app/verify/certificate/verification';

describe('public certificate verification helpers', () => {
  it('normalizes certificate numbers for lookup and canonical links', () => {
    expect(normalizeCertificateNumber('  kml-2026-ab12  ')).toBe('KML-2026-AB12');
    expect(getCertificateVerificationPath(' kml-2026-ab12 ')).toBe('/verify/certificate/KML-2026-AB12');
  });

  it('formats valid dates and preserves malformed API values', () => {
    expect(formatVerificationDate('2026-07-29T00:00:00.000Z', 'ru')).toContain('2026');
    expect(formatVerificationDate('not-a-date', 'ru')).toBe('not-a-date');
    expect(formatVerificationDate(null, 'ru')).toBe('');
  });
});
