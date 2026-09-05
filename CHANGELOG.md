# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Security: exclude local environment files, private-key material, dependency
  trees and test/build caches from Docker build contexts; the immutable-image
  workflow now blocks images that contain local env files or run as the wrong UID.
- Security: run the API/worker image as fixed non-root UID/GID 10001 and confine KZ
  release services with a read-only rootfs, bounded `/tmp`, dropped capabilities and
  `no-new-privileges`.
- Security: remove repository-known MinIO credentials; local Compose now requires
  operator-supplied non-empty root credentials before service creation.
- Security: upgrade vulnerable Python runtime/test dependencies and add a blocking,
  lock-derived production dependency audit to CI with no advisory ignores.
- Security: keep tenant SMTP transport exception details out of API responses and
  integration-audit metadata while preserving a stable error category.

### Added

- Methodologist reminder settings and on-demand status history on recurring-rule
  cards, with 1–30-day validation and reminder-only updates; delivery stays off
  globally until a separately accepted rollout.
- Disabled-by-default recurring-learning reminder backend: occurrence-bound
  outbox, bounded claims/retries, methodologist rule settings/statuses, safe
  email delivery and tenant-purge guards (additive migration 0152). Production
  activation and live-provider acceptance remain separately gated.
- Training-log recurring-cycle deadlines, an overdue filter/count and matching
  CSV fields; completed, skipped/cancelled and legacy assignments are handled
  explicitly. Deadline badges remain compatible with older API payloads.
- Document catalog provenance showing the tenant-local uploader display name
  and the existing creation date/time without exposing user IDs or email.
- Render-like KZ release plane with immutable GHCR image digests, protected
  exact-CI deployment manifests, two API slots, synchronized workers,
  fail-closed rollback, encrypted CT125 backup gating and append-only evidence.
- Protected release-plane self-upgrade bundles with exact CI/current-controller
  identity, fixed destinations, atomic installation, rollback and readback, plus
  an idempotent persistent synthetic production smoke-tenant provisioner.

### Changed

- The public login page no longer advertises the separate platform-superadmin
  entry point; existing superadmins continue to use the standard email/password
  login flow.
- Workforce navigation now keeps positions, employee groups and candidate
  assessments inside an expandable staff section instead of presenting every
  destination as a separate top-level sidebar item.
- Public trial registration no longer asks for or creates a password; verified
  owners sign in again with a one-time email code, while existing password-based
  accounts remain compatible.
- Course creation now exposes the existing feature-gated YouTube caption
  analysis flow and returns confirmed imports to generation as selected sources.

### Fixed

- Opening course generation now restores only an active job for the current
  tenant; an older failed or cancelled job no longer forces a new form onto the
  generation-progress step.
- KZ release controller now supports VM126's stock Python 3.10 runtime, and the
  protected production workflow invokes only the installed fixed-command wrapper.
- AI-generated quizzes now keep concise source-grounded answers separate from
  evidence excerpts, reject answer-length clues and implausible distractors,
  accumulate only independently validated questions across bounded retries, and
  require explicit methodologist review before course publication.
- Superadmin tenant deletion now handles published immutable course releases
  through an exact-tenant, slug-confirmed security-definer path while preserving
  the normal immutability guard and the protected production tenant.

### Security

- Hardened SCORM 1.2 package intake against unsafe archive paths, duplicate or
  ambiguous entries, encrypted and symbolic-link members, decompression bombs,
  oversized manifests and XML entity/DTD expansion before any persistent write.
- SCORM progress commits now accept only bounded SCORM 1.2 CMI fields with
  scalar string values, normalized completion statuses and cumulative state
  limits; an ingress guard rejects oversized bodies before decoding, row locks
  serialize concurrent commits, and rejected payloads leave attempts unchanged.
- The LMS frontend now applies one tested security-header policy to every route,
  including CSP anti-framing and resource boundaries, MIME sniffing protection,
  referrer and permissions restrictions, and HSTS.
- Browser refresh sessions now use one policy for exact trusted-Origin and
  Fetch Metadata checks, production JSON-only mutations, same-site secure
  cookies, symmetric deletion and production rejection of body-carried refresh
  tokens across login, OTP, role switch, invitation and trial-registration flows.

## [0.2.0] - 2026-08-31

### Added

- Authenticated question-editor assistant preview endpoint with server-derived
  tenant/actor authority, explicit impersonation rejection, and bounded typed
  error responses.
- Product versioning foundation: `VERSION` file, `CHANGELOG.md`,
  `docs/releases/` documentation, release-note template, deterministic
  version-consistency validation script and focused tests.
- Multi-document course generation with a five-source limit, aggregate source
  budget, topic and language preflight, order-insensitive duplicate admission,
  and explicit mixed-language confirmation.
- Feature-flagged YouTube caption import: validated YouTube URLs are processed
  by a bounded worker, persisted as ordinary documents, deduplicated per
  tenant, and handed to the existing document indexing pipeline.
- Reusable Russian-language guide for introducing product versioning into
  agent-managed projects.

### Changed

- Document library can offer a YouTube source flow with RU, KK, and EN caption
  preference when the backend feature flag is enabled.
- Methodologist navigation now follows the operational sequence from source
  documents and course creation through assignment, employees, and results;
  employee structure and employee groups are adjacent, and the staff menu item
  remains active across structure and import tabs.
- Self-service trial owners now start in the methodologist workspace while
  retaining a separate administrator role for tenant configuration.
- Financial-sector course blueprints are visible only to tenants explicitly
  classified as financial organizations by a platform superadmin.
- Contextual help no longer repeats its purpose block, and retention help now
  reflects the methodologist's read-only policy view instead of suggesting
  unavailable policy mutations.

### Fixed

### Security
