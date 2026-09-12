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

    expect(rules).toEqual([{ source: '/:path*', headers: buildSecurityHeaders({}) }]);
  });
});
