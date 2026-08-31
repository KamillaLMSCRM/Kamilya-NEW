# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Render-like KZ release plane with immutable GHCR image digests, protected
  exact-CI deployment manifests, two API slots, synchronized workers,
  fail-closed rollback, encrypted CT125 backup gating and append-only evidence.

### Changed

### Fixed

### Security

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
