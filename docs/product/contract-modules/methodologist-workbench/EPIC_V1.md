# Methodologist workbench — EPIC V1

## Identity

| Field | Value |
|---|---|
| Epic ID | METHOD-WORKBENCH |
| Status | Draft; only COMMAND-PLAN foundation accepted for implementation |
| Root owner | root: contracts, integration, stop decisions |
| Product owner | Human Kamilya owner in this chat |
| Approved by | Owner: product direction and stepwise work 2026-10-01; root: pure foundation only |
| Document / template version | V1 / V2 |
| Supersedes / reason | None / initial product and module boundaries |
| Decision date | 2026-10-01 |
| Change control | Proposal → root impact review → owner decision if scope/cost/data/production changes → versioned addendum or V2; preserve V1 |

## User-visible objective and success evidence

A methodologist gives a text/voice instruction with source documents, reviews
the proposed change, and gets a verifiable course/assignment result in their
active tenant. Evidence: actual draft, reviewed edits, immutable published
version, exact enrollment recipients/deadline and delivery receipt; then learner
completion/evidence. A transcript, AI answer or HTTP 200 is insufficient.

## Explicit exclusions

No autonomous publication, human-review bypass, future-member assignment rule,
arbitrary tools/SQL, deletion, admin-role capability union, cross-tenant actions,
new paid resources, provider migration or production deployment authority.
Voice approval, live calls, TTS and proactive automation are deferred.

## Roles and authority

| Role | Named owner | Accountable for / allowed | Forbidden |
|---|---|---|---|
| Root / workbench module owner | root | Shared contracts, local implementation, integration and evidence | Silent domain/billing/production expansion |
| Speech module owner | root until bounded implementation packet | Benchmark and intake contract | Unapproved audio processing/resource creation |
| Product owner | Human owner | Outcome, material business decisions, paid/data/production approval | Ambient authority |
| Reviewer | workbench_inventory leaf agent | Independent source/contract review, read-only | Scope rewrite or domain mutations |

## End-to-end states

```text
input → clarification_needed → preview_ready → confirmed → executing
                                                     → succeeded / failed / partially_succeeded
preview_ready → stale / expired / cancelled → new revision or terminal receipt
```

V1 foundation implements neither persistence nor this workflow; it validates
one fully resolved step and evaluates confirmation. Each later side-effectful
step gets a fresh plan. Already completed generation is not rolled back because
assignment failed. No whole-chain atomicity promise.

## Critical journeys

See [acceptance](acceptance/CRITICAL_JOURNEYS_V1.md). CJ-01 draft creation,
CJ-02 editing, CJ-03 publish, CJ-04 one-time assignment, CJ-05 stale/retry,
CJ-06 tenant/role denial, CJ-07 uncertain speech, CJ-08 partial failure.

## Directed module map and interfaces

```text
speech intake → edited transcript → workbench
text/document references → workbench
workbench → existing AI/course/editor/enrollment use cases
existing use cases → jobs/receipts → workbench display
```

Receipt reads do not authorize a second mutation. No circular ownership.
The shared seam is [COMMAND-PLAN V1](contracts/COMMAND_PLAN_V1.md).
No new service boundary per UI button. [Module index](MODULE_INDEX.md).

## Existing-module impact matrix

| Module | Planned class / change, not yet authorized write | Negative space | Regression |
|---|---|---|---|
| AI generation/jobs | Consumer + future operation/job dedup seam | Quotas, cancellation, provider routing | Existing generation/unit + dedup seam |
| Courses/review/publish | Future interface addendum: expected snapshot under existing lock and publish side-effect preview | Expert/quiz/approval gates, immutable releases | Publish concurrency/stale/review tests |
| Editor assistant | Future bounded apply contract after preview | Source grounding and applicability | Stale patch/new draft tests |
| Enrollments | Future one-time audience snapshot/idempotency receipt seam | Tenant ownership, active learner/access rules, outbox | Duplicates, race, cross-tenant tests |
| Departments / positions | Read-only canonical UUID/member lookup | No auto-create, DepartmentCourse rule or recompute writes | Assert no rule creation |
| Web | Future panel; canonical manual routes unchanged | Session lifecycle, mobile and role boundaries | Browser desktop/mobile/reload |
| Billing/providers/landing/CRM | None | Entirely unchanged | Diff/scope check |

Current write scope is NEW pure module/tests and these docs/backlog only.
Every integration above needs its own frozen impact addendum before neighbor
source changes. Unlisted impacts stop work.

## Data, security, migration and retention

Foundation: frozen in-memory objects only; no tables, routes, storage or network.
Server-owned actor/tenant and entity snapshots must never come from model output.
Future durable plans/receipts belong to workbench: tenant_id, ownership, RLS/FORCE
RLS, no BYPASSRLS, cross-tenant tests, expand migration/retention/rollback contract
required before implementation. Audio TTL/data route remain unapproved; no raw
audio retention by default. No payload/PII logging. Document instructions cannot
change tools or permissions. Only active methodologist role is eligible.

## Verification and allocation

| Level | Required evidence |
|---|---|
| Foundation | Canonical unit wrapper; strict payload/schema/fingerprint/confirmation cases; Ruff/Mypy |
| Seam/neighbor | Producer-consumer tests and impact matrix regression when integrated |
| DB | Approved isolated Supabase DEV migrations/RLS/ownership/concurrency |
| Integration | All critical journeys and approved real STT/model benchmark |
| Release | Exact candidate CI/version/image, Test Runner packet and Release Runner preflight |
| Production | Fresh authorized release, independent identity readback, root live QA flow |

Root owns shared writes; cheap leaf inventory/review owns no writes. Later leaf
UI/fixtures/tests packets get disjoint write sets and English-only five-field
handoffs. At most two concurrent workers. No provider actions delegated by this
document. Expected foundation map: plan_contract → standard library + Pydantic;
tests → plan_contract; no existing domain import edges.

## Rollout, Ready and Done

Foundation Ready: accepted COMMAND-PLAN and WORKBENCH foundation mini-spec,
exact write scope and tests; parent epic remains Draft pending integration seams.
Whole epic Ready additionally requires speech decision, all integration mini-spec
addenda, ownership/migration and executable seam tests.

Feature flag off by default when HTTP/UI arrives; one DEV chain candidate then
fresh production approval. Stop on unlisted writes, stale plan, missing ownership,
capacity/billing/data ambiguity or failed hard gate. Rollback disables the new
surface without deleting course/enrollment history. Whole epic Done requires
critical journeys, exact deployed revision/readback, live business flow, and
updated active docs. Foundation PASS alone is not epic Done.
