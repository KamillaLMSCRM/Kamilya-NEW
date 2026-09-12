# SEC-RV-001 impact addendum: frontend header integration v1

Status: Accepted
Owner: root

## Owned files

- `apps/web/next.config.js`
- `apps/web/security-headers.js`
- `apps/web/tests/securityHeaders.test.ts`

## Compatibility envelope

- `connect-src`: same origin plus exactly the API origin selected for that
  build. Production selects `https://api.kml.kz`; the isolated DEV build may
  select its explicit Render development API without broadening production CSP.
- `frame-src`: same origin and `https://scorm.kml.kz` only.
- images: same origin and data/blob only; the retired legacy LMS/CDN hostnames
  are not trusted runtime dependencies.
- scripts/styles: same origin plus inline compatibility required by the current
  Next.js application.

Any additional analytics, CDN, frame or API origin requires a new addendum.
