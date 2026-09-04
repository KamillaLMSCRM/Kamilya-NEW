# SEC-RV-001 security remediation chain

## Identity

| Field | Value |
|---|---|
| Epic ID | `SEC-RV-001` |
| Status | Accepted |
| Root owner | Codex root agent; module map, shared seams, integration, release gates |
| Product owner | Kamilya product owner (user) |
| Approved by | Product owner via `приступай` |
| Reviewer | `Kamilya — Security Re-Verification & Remediation Plan` independent security task |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Reason | Initial security-remediation contract |
| Decision date | 2026-09-04 |
| Change control procedure | Module owner proposes evidence; root reviews; product owner approves material scope or production; accepted changes create V2 or an impact addendum |

## User-visible objective

Tenant-uploaded SCORM 1.2 packages and learner progress commits are accepted only
inside explicit resource budgets and safe formats, while valid packages continue to
import, launch, resume, complete and issue certificates through the existing isolated
SCORM origin.

## Success evidence

- Malicious XML, unsafe archives and unsupported SCORM versions are rejected before
  course, storage or package writes.
- Unknown, nested or over-budget CMI commits are rejected before attempt mutation.
- Existing SCORM 1.2 import, launch, commit and completion contracts remain green.
- The exact release candidate passes the risk-based security suite; production is not
  claimed until its exact API/frontend/worker/DB identity and browser flow are read back.

## Explicit exclusions

- Browser-session policy, frontend CSP, storage backend selection, container identity,
  supply-chain gates and production deployment are later waves.
- No provider, DNS, database, tenant, credential, billing or production mutation.
- No SCORM 2004 support and no widening of roles or tenant access.

## Roles and authority

| Role | Named owner | Accountable for | Allowed decisions | Forbidden actions |
|---|---|---|---|---|
| Root owner | Codex root agent | Contracts, shared router/schema/dependencies, combined diff and gates | Internal implementation preserving this V1 | Production or material scope expansion without fresh authority |
| Module owner | Codex root agent | B1/B2 implementation and focused evidence | Internal design behind accepted interfaces | Unlisted module, migration or neighboring invariant change |
| Product owner | User | Objective, priority and production authority | Material business/scope decisions | Implicit approval from reports or runtime state |
| Reviewer | Independent security task, then root re-verification | Contract and security disposition | Report findings and NO-GO/GO | Treat its own report as executable proof |

## End-to-end states

```text
untrusted ZIP -> validated SCORM 1.2 package -> existing import persistence
untrusted CMI patch + persisted CMI -> validated normalized patch -> atomic existing attempt commit
rejection -> stable 400/413/422 -> no course/storage/package/attempt mutation
```

## Critical journeys

| ID | Starting state | Action | Expected terminal evidence |
|---|---|---|---|
| CJ-01 | Authorized methodologist with valid SCORM 1.2 ZIP | Import and launch | Course/package stored once; isolated-origin launch remains usable |
| CJ-02 | Active scoped learner attempt | Commit valid progress then completion | Progress persists; completion/certificate remains idempotent |
| CJ-03 | Authorized uploader with adversarial ZIP/XML | Import | Stable rejection before any durable or storage side effect |
| CJ-04 | Active scoped attempt with invalid/oversized CMI | Commit | Stable rejection and unchanged persisted attempt |

## Module map

```text
SCORM import route -> ScormPackageIntake V1 -> ValidatedScormPackage -> existing import persistence
SCORM commit route -> CmiCommitPolicy V1 -> NormalizedCmiPatch -> existing attempt persistence/completion
```

## Module index

| Module ID | Responsibility | Active mini-spec | Data owner | Writer |
|---|---|---|---|---|
| `SCORM-PACKAGE-INTAKE` | Validate uploaded bytes, archive and manifest | `modules/SCORM_PACKAGE_INTAKE_V1.md` | Stateless validation result | Module only |
| `CMI-COMMIT-POLICY` | Validate and normalize a bounded CMI merge | `modules/CMI_COMMIT_POLICY_V1.md` | Stateless patch/result | Module only |

## Interface contracts

| Contract ID | Producer | Consumer | Version | Compatibility rule |
|---|---|---|---|---|
| `SCORM-INTAKE` | Import route | `ScormPackageIntake` | V1 | Valid SCORM 1.2 metadata remains semantically compatible |
| `CMI-PATCH` | Commit route | `CmiCommitPolicy` | V1 | Supported canonical SCORM 1.2 writable fields remain accepted |

## Existing-module impact matrix

| Existing module | Impact class | Planned change | Must remain unchanged | Regression check |
|---|---|---|---|---|
| SCORM router | Interface | Delegate validation through two deep modules | Routes, auth, tenant checks, isolated origin, completion | SCORM focused and completion-boundary tests |
| SCORM schemas | Consumer | Request remains transport-only input | Response shape and route path | Schema/route tests |
| Backend dependencies | Interface | Direct pinned-compatible `defusedxml` runtime dependency | Existing dependency resolution | Poetry lock/install and import test |
| Course/storage persistence | None | None | No writes before intake success; rollback behavior | Rejection side-effect contract |
| Enrollment/certificate | None | None | Completion and idempotency | Existing SCORM E2E/completion tests |
| Tenant/RLS/auth | None | None | Current scoped token and tenant ownership | Existing security regressions |
| Frontend/SCORM bridge | None | None | Current payload format and isolated frame flow | Existing launch-shell tests |

Unlisted modules are forbidden scope for this V1.

## Data and migration plan

Both modules are stateless and introduce no migration. Existing CMI is not rewritten.
The first release adds application guards only. Any database `CHECK`, cleanup or
backfill requires an existing-row inventory and a new root-owned migration addendum.

## Security and privacy invariants

- Never parse XML with external entities, DTD processing or entity expansion enabled.
- Validate the complete archive before storage or database side effects.
- Never log archive content, manifest XML, CMI values, tokens, secrets or tenant PII.
- CMI validation occurs before mutating ORM state.
- Tenant context, scoped token, enrollment, course and package checks remain server-owned.

## Verification plan

| Level | Scope | Command or evidence | Required result |
|---|---|---|---|
| Focused | B1/B2 | `poetry run pytest tests/unit/test_scorm_package_intake.py tests/unit/test_cmi_commit_policy.py -q` | PASS |
| Contract | Routes to modules | SCORM parse/security/completion tests | PASS |
| Neighbor | Auth/origin/completion | Existing focused SCORM suite | PASS |
| Integration | Persisted attempt/import | Existing SCORM integration on disposable PostgreSQL | PASS or explicitly NOT VERIFIED |
| Release | Candidate | Quality baseline, dependency and security gates | PASS |
| Production | Exact revision and flow | Approved exact-SHA benign/adversarial browser readback | PASS before sign-off |

## Agent allocation

| Agent | Read scope | Write scope | Forbidden scope | Completion packet |
|---|---|---|---|---|
| Codex root | Kamilya-NEW source/docs/tests | This epic, SCORM modules/router/schema tests, backend dependency manifests, changelog | Production/providers/DB/migrations/other modules | Diff, focused/neighbor/full gate evidence and residual risks |

## Rollout and stop conditions

Implementation stops for an unlisted module, migration, unknown existing-data
compatibility issue, weakened auth/RLS/origin control, unavailable critical test that
would be silently replaced, unrelated worktree change or production authority need.
Unsafe parsing has no feature-flag fallback. Production rollout remains separately
approval-gated and rolls back by exact prior image only for operational failure.

## Definition of Ready

- Objective, roles, interfaces, data ownership and exclusions are explicit.
- B1/B2 V1 mini-specs and impact addenda are accepted.
- Graph-derived candidates were checked against current source and tests.
- Test seams are `inspect(...)` and `validate(...)` as approved by the product owner.

## Definition of Done

- B1/B2 interface, contract and neighbor tests pass.
- No unplanned dependency or file change exists.
- Graphify is updated and compared with this module map.
- Integration/release/production checks are either proven or explicitly remain open;
  local success is not presented as production completion.
