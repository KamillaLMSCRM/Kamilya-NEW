# Completion form field builder — bounded implementation contract

Status: accepted for local implementation; no production publication authorized by this task.

## User outcome

An administrator selects the available fields of the existing printable completion form, previews and downloads a sample, then saves a tenant-owned template. The learner receives the selected form on a new course completion. This is not a certificate redesign or a regulated attestation/signature service.

## Contract

- Extend `PrintFormEvidence` and the existing tenant JSON settings with nullable `selected_fields`. `null` preserves the legacy renderer and historical manifest serialization (`exclude_none=True`). Existing event snapshots remain immutable.
- Explicit selection is a unique ordered list of server-allowlisted IDs. `employee_name`, `course_title`, and `test_results` are required. Unknown fields, duplicates and missing required fields return validation errors. No arbitrary HTML, code, expression or database-column selection.
- GET `/v1/training-evidence/form-fields` returns `{fields: [{id, label, group, required}], default_selected_fields: string[]}` to the existing admin role only. Existing settings GET/PUT/preview keep their authorization and shapes, adding only `selected_fields`.
- Available IDs: `organization`, `employee_name`, `personnel_number`, `department`, `position`, `course_title`, `course_version`, `assigned_at`, `due_at`, `test_results`, `test_title`, `test_score`, `test_threshold`, `test_completed_at`, `test_duration`, `generated_at`, `employee_confirmation`, `employee_signature`, `representative_signature`, `footer_note`.
- Default selection: organization, employee_name, course_title, course_version, test_results, test_title, test_score, test_threshold, test_completed_at, generated_at, employee_confirmation, employee_signature, representative_signature, footer_note.
- Test titles come from verified quiz-attempt snapshots only for newly configured forms; legacy manifests do not acquire new historical fields. Standalone quiz-event template issuance is outside this first course-completion package.
- Results show every recorded attempt with its own outcome, not a guessed aggregate. Missing/unknown outcomes are explicitly unconfirmed. Zero scores and failed attempts must remain visible. No attempts is not evidence of passing a test.
- Preview for an explicit selection contains only the configured form, not the full audit act. Learner export uses the same renderer for explicit selections. Full methodologist PDF/ZIP remains a complete audit record, with the selected form appended; public redaction is unchanged.
- Optional personnel number, department and position are current employee profile values at export, not historical employment facts. UI and form explain that limitation. No email/phone fields are added.
- Templates are snapshotted at completion using the existing workflow. Pre-snapshot legacy events retain the legacy fallback rather than adopting a new field selection retroactively.

## Ownership and failure behavior

Root owns API schemas, catalog, validation, renderer, export projection, tests and integration. A bounded UI leaf may own only the existing settings page and its dedicated tests. Failed settings/catalog loading disables editing/saving; stale previews cannot be downloaded as if they match the current draft. No migration, billing change, permissions expansion, voice, model routing or production mutation.

## Verification gates

Test selection validation, settings merge/snapshot roundtrip, missing/failed/zero result rendering, optional field omission, historical serialization and full audit/public export regressions. Render PDF sample pages and visually inspect them. Run focused API unit suites, web checks and applicable quality checks. DEV and production/live checks must be reported separately from local verification.

## Local verification on 2026-10-18

- 71 focused API tests passed: field validation/catalog, in-process HTTP admin/role/tenant-context guards, save/reload/preview, completion workflow snapshot, learner projection, verified quiz titles, full/public evidence exports and neighboring signed-copy/share/procedure tests. Injected-identity HTTP tests are not live JWT or database RLS evidence.
- 8 focused React tests passed, including the existing PDF-preview regressions; TypeScript and targeted ESLint passed. These are component tests, not a live browser acceptance.
- Committed Python quality baseline passed without new violations (ruff 1006 / mypy 2191 are existing baseline counts, not new defects).
- Synthetic legacy form PDF is byte-identical to the original renderer at base `3f0dd3f823f786df2699695e8e92bd4163ea2400`; SHA256 `faa504a27b14be685b4fc70dc9503a66d95c384e9be6999d06a189beb0d8fc32`.
- Two synthetic reference forms generated using `scripts/dev/render_completion_form_samples.py --output-dir output/pdf`; both single-page PDFs rendered with Poppler and visually inspected. All-fields sample includes failed zero-score and passed attempts and Kazakh name glyphs.
- CodeGraph navigation preparation returned runtime missing; bounded SOURCE_FALLBACK used. No index or graph inference claimed.
- Not run: Supabase DEV integration/RLS, shared DEV deployment/browser completion cycle, production deployment or live acceptance. No provider/infrastructure/DB/billing changes, new accounts, voice or model-routing changes.

Next gate: shared DEV admin configure/save/reload; new synthetic course completion; learner PDF matches snapshotted selection; change current template and re-download original completion; verify methodologist complete audit and cross-tenant denial. Publication requires owner approval for this package.
