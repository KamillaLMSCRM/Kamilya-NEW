# CMI commit policy mini-spec

## Identity

| Field | Value |
|---|---|
| Module ID | `CMI-COMMIT-POLICY` |
| Name | `CmiCommitPolicy` |
| Status | Accepted |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | Product owner via SEC-RV-001 approval on 2026-09-04 |
| Change control | Proposal -> root review -> V2/addendum or cancellation |
| Owning epic | `SEC-RV-001` |

## Responsibility [Core]

Validate, normalize and merge one bounded SCORM 1.2 CMI patch before any persisted
attempt mutation.

## Non-responsibilities [Core]

Token/enrollment/tenant authorization, database commit, completion, certificates and
browser runtime remain owned by existing SCORM modules.

## User-visible contribution [Core]

Learner progress continues to save while malformed or abusive payloads cannot create
unbounded JSONB state or unsupported keys.

## External interface [Core]

```text
CmiCommitPolicy.validate(raw_patch, existing_state, raw_content_length=None)
  -> NormalizedCmiPatch
```

The result contains normalized patch and merged state. Errors expose stable code,
HTTP 413/422 status and public detail.

## Inputs and outputs [Core]

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | Raw CMI map + existing state + optional length | V1 | Grammar, scalar type, count and byte budgets | Learner progress; never logged |
| Output | Normalized patch + merged state | V1 | Deterministic canonical status values | Learner progress |

## Data ownership [Core]

Stateless policy result. `ScormAttempt` remains owned and written by the existing commit
route after successful validation. Tenant ownership/RLS are unchanged.

## Invariants [Core]

- Input and existing mappings are not mutated.
- Only supported flat SCORM 1.2 writable keys are accepted.
- Values are strings and byte-bounded; nested values are rejected.
- Patch, raw request estimate and cumulative merged state stay within budgets.
- Rejection precedes ORM field mutation and commit.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| Existing attempt state | Valid patch | Normalized merged state | All policy checks pass | Return result only |
| Existing attempt state | Invalid patch | Rejected | Any check fails | None |

## Idempotency and concurrency [Extended]

Validation is deterministic. Reapplying the same patch produces the same merged state.
Database locking/concurrent commit ordering remain an integration concern and require a
disposable-PostgreSQL gate before release.

## Error modes [Core]

| Error | Class | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| Unsupported key/type/status/nesting | Permanent | HTTP 422 | Correct payload | Stable policy code |
| Entry/value/request/cumulative budget | Permanent | HTTP 413 | Smaller payload/state plan | Stable budget code |

## Dependencies and adapters [Extended]

In-process Python only. No adapter is needed.

## Forbidden dependencies and side effects [Extended]

No DB, auth, network, storage, logging of values, audit payload, completion or certificate
side effect.

## Existing-module impact addendum [Extended]

See `../impact/CMI_COMMIT_INTEGRATION_V1.md`.

## Security and privacy [Core]

The module receives already-authorized input but does not trust its shape. It exposes
only stable codes and counts; raw keys/values are not logged or returned in errors.

## Observability [Extended]

Metrics may include error code and bounded counts/bytes only. CMI values, learner data
and tokens are forbidden.

## Performance and configuration [Extended]

Initial compatibility envelope: 256 entries; 128-byte keys; 8 KiB ordinary values;
64 KiB `cmi.suspend_data`; approximately 128 KiB raw commit; 256 KiB cumulative state.
Any widening requires observed-data evidence and V2/addendum approval.

## Verification [Core]

Interface tests cover canonical fields, indexed objective/interaction fields, aliases,
unknown/nested/non-string input, each budget, status normalization, immutable inputs,
idempotent merge and unchanged route state on rejection.

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | SCORM schemas/router/models/tests and current ingress config |
| Write scope | `app/modules/scorm/cmi_policy.py`, SCORM router/schema/tests, changelog |
| Forbidden scope | DB migrations, proxy, auth, frontend, production, historical data rewrite |
| Required checks | Policy interface tests, route atomic rejection, existing SCORM completion/E2E tests |
| Stop conditions | Existing valid package requires an unlisted field/budget or migration |
| Handoff evidence | Exact tests and explicit DB/browser/production gaps |

## Rollout and rollback [Extended]

Application guard is backward-compatible for supported fields. No fail-open flag.
Operational rollback uses prior image while retaining evidence of rejected payloads only
as safe aggregate codes, never content.

## Definition of Ready [Core]

Grammar, limits, merge semantics, errors, write scope and stop conditions are accepted.

## Definition of Done [Core]

Policy and route contract tests pass; invalid input cannot mutate the attempt; existing
completion behavior remains green; DB concurrency remains explicitly gated until tested.
