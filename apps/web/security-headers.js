const PRODUCTION_API_ORIGIN = 'https://api.kml.kz';

const productionDirectives = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "media-src 'self' blob:",
  `connect-src 'self' ${PRODUCTION_API_ORIGIN}`,
  "frame-src 'self' https://scorm.kml.kz",
  "worker-src 'self' blob:",
  "manifest-src 'self'",
];

function resolveApiOrigin(apiUrl) {
  if (!apiUrl) return PRODUCTION_API_ORIGIN;

  try {
    const parsed = new URL(apiUrl);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:'
      ? parsed.origin
      : PRODUCTION_API_ORIGIN;
  } catch {
    return PRODUCTION_API_ORIGIN;
  }
}

function buildSecurityHeaders({
  isDevelopment = process.env.NODE_ENV === 'development',
  apiUrl,
} = {}) {
  const apiOrigin = resolveApiOrigin(apiUrl);
  const directives = productionDirectives.map((directive) => {
    if (directive.startsWith('connect-src')) {
      return `connect-src 'self' ${apiOrigin}`;
    }
    if (isDevelopment && directive.startsWith('script-src')) {
      return `${directive} 'unsafe-eval'`;
    }
    return directive;
  });

  return [
    { key: 'Content-Security-Policy', value: directives.join('; ') },
    { key: 'X-Frame-Options', value: 'DENY' },
    { key: 'X-Content-Type-Options', value: 'nosniff' },
    { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
    {
      key: 'Permissions-Policy',
      value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()',
    },
    { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
  ];
}

module.exports = { buildSecurityHeaders, resolveApiOrigin };
