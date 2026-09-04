# SEC-RV-001 impact addendum: frontend header integration v1

Status: Accepted
Owner: root

## Owned files

- `apps/web/next.config.js`
- `apps/web/security-headers.js`
- `apps/web/tests/securityHeaders.test.ts`

## Compatibility envelope

- `connect-src`: same origin, `https://api.kml.kz`, the explicit legacy Render
  development API and secure WebSocket transport.
- `frame-src`: same origin and `https://scorm.kml.kz` only.
- images: same origin, data/blob and `https://cdn.lms.kml.kz`.
- scripts/styles: same origin plus inline compatibility required by the current
  Next.js application.

Any additional analytics, CDN, frame or API origin requires a new addendum.
