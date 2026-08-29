# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Fixed

### Security
