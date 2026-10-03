import { describe, expect, it } from 'vitest';

const { buildSecurityHeaders, resolveApiOrigin } = require('../security-headers');
const nextConfig = require('../next.config.js');

describe('frontend security header policy', () => {
  it('defines the complete bounded baseline', () => {
    const headers = Object.fromEntries(
      buildSecurityHeaders().map(({ key, value }: { key: string; value: string }) => [key, value]),
    );

    expect(headers['Content-Security-Policy']).toContain("frame-ancestors 'none'");
    expect(headers['Content-Security-Policy']).toContain("object-src 'none'");
    expect(headers['Content-Security-Policy']).toContain("base-uri 'self'");
    expect(headers['Content-Security-Policy']).toContain("form-action 'self'");
    expect(headers['Content-Security-Policy']).toContain('connect-src');
    expect(headers['Content-Security-Policy']).toContain('https://api.kml.kz');
    expect(headers['Content-Security-Policy']).not.toContain('kamilya-lms-api.onrender.com');
    expect(headers['Content-Security-Policy']).toContain("img-src 'self' data: blob:");
    expect(headers['Content-Security-Policy']).not.toContain('cdn.lms.kml.kz');
    expect(headers['Content-Security-Policy']).toContain("frame-src 'self' https://scorm.kml.kz");
    expect(headers['Content-Security-Policy']).not.toContain('frame-src *');
    expect(headers['X-Frame-Options']).toBe('DENY');
    expect(headers['X-Content-Type-Options']).toBe('nosniff');
    expect(headers['Referrer-Policy']).toBe('strict-origin-when-cross-origin');
    expect(headers['Permissions-Policy']).toContain('camera=()');
    expect(headers['Strict-Transport-Security']).toContain('max-age=31536000');
  });

  it('allows only the API origin selected for a non-production build', () => {
    const headers = Object.fromEntries(
      buildSecurityHeaders({ apiUrl: 'https://kamilya-lms-api.onrender.com/api' }).map(
        ({ key, value }: { key: string; value: string }) => [key, value],
      ),
    );

    expect(resolveApiOrigin('https://kamilya-lms-api.onrender.com/api')).toBe(
      'https://kamilya-lms-api.onrender.com',
    );
    expect(resolveApiOrigin('javascript:alert(1)')).toBe('https://api.kml.kz');
    expect(headers['Content-Security-Policy']).toContain(
      "connect-src 'self' https://kamilya-lms-api.onrender.com",
    );
    expect(headers['Content-Security-Policy']).not.toContain('https://api.kml.kz');
  });

  it('applies the policy to every frontend route', async () => {
    const rules = await nextConfig.headers();

    expect(rules[0]).toEqual({ source: '/:path*', headers: buildSecurityHeaders({}) });
    expect(rules.slice(1).map((rule: { source: string }) => rule.source)).toEqual([
      '/admin/certificates/settings',
      '/admin/training-evidence/settings',
    ]);
    for (const rule of rules.slice(1)) {
      expect(rule.headers).toHaveLength(1);
      expect(rule.headers[0].key).toBe('Content-Security-Policy');
      const baseline = buildSecurityHeaders({})[0].value;
      expect(rule.headers[0].value).toBe(baseline.replace(
        "frame-src 'self' https://scorm.kml.kz",
        "frame-src 'self' blob: https://scorm.kml.kz",
      ));
    }
  });

  it('limits the preview exception to frame-src without weakening the baseline', () => {
    const baseline = buildSecurityHeaders({ isDevelopment: false });
    const preview = buildSecurityHeaders({ isDevelopment: false, allowPdfPreview: true });
    expect(preview.slice(1)).toEqual(baseline.slice(1));
    expect(preview[0].value).toBe(baseline[0].value.replace(
      "frame-src 'self' https://scorm.kml.kz",
      "frame-src 'self' blob: https://scorm.kml.kz",
    ));
    expect(preview[0].value).toContain("frame-ancestors 'none'");
    expect(preview[0].value).toContain("object-src 'none'");
    expect(preview[0].value).not.toContain("frame-src 'self' data:");
  });
});
