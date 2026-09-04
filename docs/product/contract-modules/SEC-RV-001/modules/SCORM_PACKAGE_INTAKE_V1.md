# SCORM package intake mini-spec

## Identity

| Field | Value |
|---|---|
| Module ID | `SCORM-PACKAGE-INTAKE` |
| Name | `ScormPackageIntake` |
| Status | Accepted |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | Product owner via SEC-RV-001 approval on 2026-09-04 |
| Change control | Proposal -> root review -> V2/addendum or cancellation |
| Owning epic | `SEC-RV-001` |

## Responsibility [Core]

Turn one untrusted uploaded ZIP into a fully validated SCORM 1.2 package result,
concentrating byte, archive, path, manifest, XML and launch-resource policy.

## Non-responsibilities [Core]

Authentication, tenant/course limits, database/storage writes, launch tokens, content
origin, asset serving, completion and certificates remain outside this module.

## User-visible contribution [Core]

Valid SCORM 1.2 packages continue to import; malformed or hostile packages fail safely
before creating partial courses or stored objects.

## External interface [Core]

```text
await ScormPackageIntake.inspect(upload, content_length) -> ValidatedScormPackage
```

The result contains immutable package bytes and typed manifest metadata. The operation
is bounded by configured limits and raises one normalized `ScormIntakeError` carrying a
stable code, HTTP status and public detail.

## Inputs and outputs [Core]

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | Upload stream + optional Content-Length | V1 | Byte budget; ZIP/archive/manifest policy | Tenant content; never logged |
| Output | `ValidatedScormPackage` | V1 | SCORM 1.2, safe normalized archive/manifest | Package bytes |

## Data ownership [Core]

Stateless. It owns only immutable validation results. No database, tenant record or
storage object is written.

## Invariants [Core]

- Every successful result passed all byte/archive/XML/version/path checks.
- Every rejection occurs before caller persistence.
- Package bytes are never logged or executed.
- A manifest is unique and its declared launch path is safe.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| Untrusted | `inspect` | Validated | All budgets and SCORM 1.2 contract pass | Return immutable result |
| Untrusted | `inspect` | Rejected | Any validation fails | None |

## Idempotency and concurrency [Extended]

Pure with respect to persistent state. Repeating the same bytes and limits produces the
same result or error. The upload stream itself is consumed once per call.

## Error modes [Core]

| Error | Class | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| Invalid length/ZIP/path/manifest/version | Permanent | Map normalized status/detail | Only with corrected package | Stable code/status |
| Byte budget exceeded | Permanent | HTTP 413 | Only smaller package | `zip_too_large` |

## Dependencies and adapters [Extended]

Direct standard-library ZIP handling and `defusedxml`. Upload streaming is supplied by
the existing FastAPI `UploadFile`; no new hypothetical port is introduced.

## Forbidden dependencies and side effects [Extended]

No DB, storage, network, auth, tenant, audit, provider, subprocess, XML schema fetch or
execution of package content.

## Existing-module impact addendum [Extended]

See `../impact/SCORM_INTAKE_INTEGRATION_V1.md`.

## Security and privacy [Core]

DTD/entities/external references are rejected. ZIP encryption, symlinks, unsafe paths,
duplicates, ambiguous manifests and expansion-budget violations are rejected. Content
and filenames are not logged by the module.

## Observability [Extended]

Caller may count stable error codes and byte/count totals, but not names, XML or bytes.

## Verification [Core]

Tests use `inspect` for benign SCORM 1.2, unsupported 2004, malformed/DTD/entity XML,
archive path/link/encryption/duplicate/budget cases, launch paths and no-side-effect
route behavior.

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | SCORM router/tests, upload ADR, dependency manifests |
| Write scope | `app/modules/scorm/package_intake.py`, SCORM router/tests, pyproject/lock/requirements, changelog |
| Forbidden scope | Auth, RLS, migrations, storage implementation, frontend, production |
| Required checks | Focused intake tests, existing SCORM parse/security tests, Ruff/mypy baseline |
| Stop conditions | New persistence/migration or incompatible valid SCORM corpus |
| Handoff evidence | Exact files, tests, unresolved integration/production gates |

## Rollout and rollback [Extended]

No unsafe-parser fallback. Operational rollback uses the prior exact image; malicious
package acceptance is not restored as a feature flag.

## Definition of Ready [Core]

Interface, limits, error contract, side-effect boundary and affected files are accepted.

## Definition of Done [Core]

Adversarial corpus and existing compatibility tests pass through `inspect`; route uses
the module; no forbidden dependency or unexpected graph edge exists.
