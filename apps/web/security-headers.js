const productionDirectives = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://cdn.lms.kml.kz",
  "font-src 'self' data:",
  "media-src 'self' blob:",
  "connect-src 'self' https://api.kml.kz https://kamilya-lms-api.onrender.com",
  "frame-src 'self' https://scorm.kml.kz",
  "worker-src 'self' blob:",
  "manifest-src 'self'",
];

function buildSecurityHeaders({ isDevelopment = process.env.NODE_ENV === 'development' } = {}) {
  const directives = isDevelopment
    ? productionDirectives.map((directive) =>
        directive.startsWith('script-src') ? `${directive} 'unsafe-eval'` : directive,
      )
    : productionDirectives;

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

module.exports = { buildSecurityHeaders };
