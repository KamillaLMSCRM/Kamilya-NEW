# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Security

## [0.4.3] - 2026-09-10

### Fixed

- Generated quiz answers must use a short exact excerpt from their lesson evidence;
  topic-word overlap no longer admits invented properties or changed numeric values.
- Quiz explanations quote the selected lesson evidence without adding a second
  model-authored factual claim. Existing review and question-quality checks remain.

## [0.4.2] - 2026-09-10

### Fixed

- Course generation from large Excel catalogs processes source topics throughout
  the document and handles long spreadsheet headings when writing lessons.
- Invalid navigation-map formatting receives one bounded retry; already validated
  batches can be reused within that same generation job.
- Generated lesson headings, lists and simple tables are displayed as readable
  content, with source HTML remaining inert text.

## [0.4.1] - 2026-09-10

### Fixed

- Large spreadsheet course sources no longer exhaust the topic-map batch budget because identical source metadata is repeated per fragment. Exact source content, provenance, coverage validation, and existing request limits are preserved.
- An overlong but otherwise valid navigation-map response gets one bounded shortening attempt before failing; source-ID groups, deadlines and output validation remain enforced.

## [0.4.0] - 2026-09-10

### Added

- Organization administrators can configure their own course/test generation and document-indexing providers separately, with encrypted write-only keys and tenant-scoped settings.

### Changed

- Course generation can use verified original source material when a compatible semantic index is unavailable; available semantic excerpts remain bound to the selected source documents.

### Fixed

- Assessment repair includes actionable answer-length feedback, caps recovered questions to the requested count, and rejects repeated questions with the same evidence and normalized correct answer.
- Large-source fallback selects whole excerpts within the request budget while retaining every document requested for the lesson.
- Semantic document search keeps query instructions separate from source material, validates vector-to-fragment ordering, and prevents mixing incompatible embedding spaces during provider fallback.

### Security

## [0.3.1] - 2026-09-09

### Fixed

- Course approval settings now load their saved server state when opening or switching courses, instead of displaying an unchecked default. Failed reads show a retry action rather than an incorrect disabled policy.
- Publication conflicts explain the required approval action in Russian, Kazakh, and English in the course list, editor, and AI-generation result screen. Separate approval remains off by default and is enforced when explicitly enabled.

## [0.3.0] - 2026-09-08

### Added

- Tenant-scoped course approval and review: methodologists can send a course to
  internal or guest reviewers, collect decisions and comments, and retain the
  review context before publication.
- Learning Insights for methodologists: inspect incorrect learner answers from
  immutable attempt evidence, compare first and latest answers, view aggregate
  question statistics, and record a follow-up status without automated actions
  or LLM calls.
- Recurring learning programs with cycle deadlines, overdue visibility, CSV
  reporting, reminder settings and delivery-status history. Global reminder
  delivery remains disabled until a separately accepted rollout.
- A public RU/KK/EN interactive learning example and a methodologist dashboard
  with real training-summary counts and clear starting paths for materials or
  ready course foundations.
- Document provenance showing the tenant-local uploader and creation time, plus
  the existing feature-gated YouTube-caption source flow.

### Changed

- AI-generated assessments require explicit methodologist review before course
  publication and keep concise answers separate from supporting excerpts.
- Public trial registration is passwordless; verified owners return through an
  email code while existing password accounts remain compatible.
- Staff-related navigation is grouped under one expandable section, and the
  public login no longer advertises a separate superadmin entry point.
- Tenant assistant responses are constrained to the tenant learning context and
  do not disclose model, provider, configuration or secret operational details.

### Fixed

- Course-generation cancellation is serialized with course persistence and is
  checked between assessment retries, preventing a cancelled job from leaving
  an unlinked course or reporting unfinished work as complete.
- New generation forms no longer reopen an old failed or cancelled job, and
  valid assessment questions can be recovered across bounded retries.
- Course approval navigation, guest-review credentials, pagination, action
  confirmations and response serialization now preserve the intended reviewer
  and tenant context.
- Browser refresh requests are serialized across tabs, responsive navigation no
  longer shifts the application shell, and learner program navigation remains
  available for active recurring programs.
- Reminder workers own their asynchronous database lifecycle, while recurring
  learning and assignment outboxes remain usable under non-bypass database
  ownership without weakening tenant boundaries.

### Security

- SCORM package intake and progress commits reject unsafe archives, XML entity
  expansion, decompression bombs, invalid fields and oversized cumulative state
  before persistent writes.
- Browser-session mutations enforce trusted origins, Fetch Metadata, secure
  same-site cookies, JSON-only production requests and symmetric token deletion.

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

[Unreleased]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.4.3...HEAD
[0.4.3]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.2.0...v0.3.0
