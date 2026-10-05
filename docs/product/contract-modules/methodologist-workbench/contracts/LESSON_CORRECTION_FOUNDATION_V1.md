# WB-LESSON-CORRECTION-FOUNDATION V1

Status: Accepted for bounded local implementation, 2026-10-05. Template V2.
Approved by: product owner continued the approved stepwise AI-driven workbench
plan ("продолжац"); root accepts this technical, non-mutating foundation only.
Root/module owner: root. Product owner: repository owner. Reviewer: independent
read-only correction inventory agents, after implementation. No new release,
provider spend, database mutation or production activation is implied.
Preserves EPIC V1, COMMAND-PLAN V1 and DOCUMENT-DRAFT V1. Change control: root
accepts versioned impact addenda before persistence, provider, HTTP or UI work.

## Responsibility, outcome and interface

One active methodologist requests a correction of one source-backed draft
lesson's text, sees the exact before/after proposal and confirms that proposal.
This foundation owns the policy separating a provider suggestion from a
permitted application plan. It is stateless and never executes the plan.

The two public policy operations are `preview_lesson_correction` and
`prepare_lesson_correction`. Inputs are a server-resolved immutable snapshot,
current tenant/actor/active role, current lesson/course/source context, aware
time, and a structured-edit provider for preview only. Confirmation accepts the
existing plan ID/revision/fingerprint DTO. Outputs are a sealed preview or the
existing non-mutating `PatchApplicationPlan`.

The context resolver (future integration, not this slice) must establish tenant
ownership of course -> module -> lesson and every source. Lesson and course
version tokens must change on any relevant edit, lifecycle, approval or source
binding change; source version/content SHA-256/index revision and exact admitted
evidence locator/hash are server-derived. Client/model IDs never establish
ownership. The foundation cannot prove that a caller resolved these correctly.

The fixed operation is exactly one `replace` on `lesson.content`, with exact
before text/hash and nonempty, changed after text/hash. No title, quiz, metadata,
source binding, approval, publication, enrollment or recipient edits are allowed.
Locale is explicit `ru`, `kk` or `en`; instruction max4000, each lesson text
max64000 characters, five unique sources, at most64 admitted evidence locators.
All cited evidence must belong to that exact admitted source/locator/hash set.
Reference membership is structural grounding, NOT proof that every generated
claim follows from a source. A model's PASS report is not semantic acceptance.
Human review and deterministic/provider quality checks remain separate gates.

## Data, states, security and errors

Workbench owns immutable in-memory snapshot/preview/fingerprint; existing
editor-assistant owns structured commands/patches and application plans. There
is no durable record, migration, retention worker or new data owner. Existing
15-minute preview lifetime is the maximum; created/expires times are aware.
Before/after text is necessary for a diff, not suitable for logs or audit events.
Only safe fixed error codes are emitted by policy; provider exception text is
not reflected. No raw instruction/source/model payload telemetry is added.

Transitions: resolved snapshot -> validated sealed preview -> confirmed pure
application plan. Wrong active role, tenant/actor, plan/revision/fingerprint,
changed lesson/course/source/evidence, expiry or invalid proposal refuses the
transition. A future or expired snapshot fails before provider work. Published
contexts fail with `new_draft_required` before provider work: creating a new
draft while retaining release/history bindings is NOT implemented here.

The seal binds the full snapshot and structured patch, including instruction,
locale, before/after content, source evidence and provenance. It is a digest,
not authentication, a signature or permission. Context comes from the server.
Pure repeated confirmation returns the same plan; it does NOT provide durable
idempotency or concurrency exclusion. Future executor must lock the owned plan
and course/lesson, re-resolve context inside that transaction and atomically
write content plus receipt. That gate cannot be replaced by these unit tests.

## Dependencies, impact and forbidden scope

| Module | Impact | Rule |
|---|---|---|
| Workbench | New pure policy | New correction contract/tests only |
| Editor assistant | Consumer | Reuse `preview_edit`, `prepare_patch_application`, immutable patch types; no edits |
| Workbench confirmation | Consumer | Reuse actor and confirmation DTOs; no change to existing operation union |
| Lessons/courses/approval/quizzes | None in this slice | No existing service, route or state changes |
| Documents/AI/jobs/budget | None in this slice | No retrieval, model call, regeneration, charge/refund or queue registration |
| UI/auth/RLS/DB/providers/infra | None | No routes, flags, migration, grants, billing or runtime writes |

The existing regeneration job is not a preview adapter: it writes lesson content
and may replace quizzes. The direct lesson PATCH is not the correction executor:
it lacks guarded version/idempotency/audit/approval-supersession semantics.
Before a persistence addendum can be accepted it must cover audit before/after
digests, exact source provenance, atomic replay/collision, approval supersession,
course review invalidation, quiz `needs_review` (never deletion), and immutable
release/enrollment/attempt preservation. Source validation stays review-required;
a provider cannot set it to verified. Existing manual editing is not redesigned
in this foundation.

Read scope: targeted workbench/editor, source and lesson/course/approval policy,
AI-COURSE-01 and named regression tests. Write scope: new
`methodologist_workbench/correction_contract.py`, its unit tests, this contract,
MODULE_INDEX and current execution plan. Root owns all writes and interfaces.
Unlisted source changes, unresolved ownership, live data/provider needs or
published-revision implementation stop this slice and require an impact addendum.

## Verification, Ready, Done and rollout

Ready: source-confirmed editor seam, fixed operation, trusted-context obligations
and explicit negative space. Focused tests use a deterministic fake provider and
the same public policy operations: exact before/after/evidence validation,
tenant/actor/role denial before provider, source/course/text staleness, expiry,
tampering, replay, scope escape, published refusal and sanitized failure.
Run existing editor patch and workbench confirmation regressions plus quality
baseline, independent review and final diff. CodeGraph source candidates must be
verified directly; one post-delta sync checks expected directed dependencies.

Done for this slice: local focused/contract regressions and independent review;
status `LOCAL_ONLY`. End-user correction remains NOT IMPLEMENTED until source
resolver/provider-quality, durable preview/apply, atomic executor and UI are
integrated, isolated DEV/RLS/concurrency tests pass, and browser acceptance
passes. AI-COURSE-01 generation behavior remains unchanged. Full journey/provider
and production gates are NOT VERIFIED by this foundation. Rollback: omit the
unreferenced policy; no deployed state or database rollback is required.
