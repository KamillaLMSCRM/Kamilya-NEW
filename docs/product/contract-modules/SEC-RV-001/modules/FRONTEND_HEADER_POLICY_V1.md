# SEC-RV-001 module: FrontendHeaderPolicy v1

Status: Accepted
Owner: bounded frontend package
Approved by: product owner through the 2026-09-04 instruction to start the remediation program

## Objective

Provide one auditable security-header policy for every Next.js route without
changing application behavior, API routing, analytics or the isolated SCORM host.

## Interface

`buildSecurityHeaders() -> Array<{ key, value }>`

`next.config.js.headers()` applies the returned headers to `/:path*`.

## Invariants

- CSP denies framing and plugins, restricts base/form/navigation resources and
  explicitly names the KZ API and isolated SCORM frame origin.
- `X-Frame-Options`, `nosniff`, strict referrer policy, bounded permissions and
  HSTS are present on all frontend routes.
- The policy contains no wildcard script, frame or connect source.
- Required Next.js inline scripts/styles remain compatible in v1; nonce-based
  removal of `unsafe-inline` requires a separate rollout contract.

## Out of scope

- API and landing repositories.
- Provider configuration and deployment.
- CSP report collection or nonce architecture.

## Verification

- Exact config-level header test.
- Existing frontend type, lint and unit suites.
- Production browser/readback remains a release gate.
