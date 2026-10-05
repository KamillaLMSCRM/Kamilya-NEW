# WB-LESSON-CORRECTION-APPLICATION V1

Status: Accepted for local implementation, 2026-10-05. Template V2.
Approved by: product owner continuation "го" after isolated preview acceptance;
root approves this bounded implementation impact. Root/module owner: root.
Product owner: repository owner. Reviewer: independent leaf and Test Runner.
Preserves FOUNDATION V1 and PREVIEW V1..V1.4. Change control: versioned addendum
before unlisted writes, public activation, new published-draft behavior or UI.

## Responsibility, interface and directed map

An ordinary active methodologist explicitly confirms the exact reviewed seal.
Apply one replacement to a source-owned draft lesson once, return a durable
receipt, and reload that receipt without reapplying. No model/provider/budget,
publication, assignment, regeneration, email or learner write during apply.
POST `/lesson-correction-previews/{plan_id}/apply` accepts existing
ConfirmationRequest(plan_id, revision, fingerprint); path/body must agree.
GET `/lesson-correction-previews/{plan_id}/application` returns the owned receipt
or404. Both use existing independent correction/workbench flags and ordinary
methodologist RBAC, no impersonation; no-store for success and failure.

Map: HTTP -> workbench application -> immutable owned preview + pure foundation
confirmation -> fresh locked course/source context -> existing lesson writer +
approval supersession + course review reset -> digest audit + application receipt
-> one commit. Domain owners do not move; application coordinates these specific
existing writer interfaces within the same transaction. No inverse dependency.

## Inputs, outputs, state and ownership

Input contains no content, sources, provider, tenant/actor or approval authority.
Output: plan_id, lesson_id, course_id, revision, fingerprint, before_sha256,
after_sha256, DB applied_at, state=applied, source_review=needs_review,
quiz_review=needs_review. Review labels describe the required review, not proof
that any quiz exists or has been reviewed. No raw lesson/instruction/source in
audit or receipt. Exact before/after remains in the immutable parent preview.
Workbench owns additive0177 `workbench_lesson_correction_applications`, PK plan_id
FK to preview with tenant-scoped parent purge cascade, actor/tenant/course/lesson,
seal/revision/digests/time. Absent -> immutable applied. No UPDATE privileges.
Preview states and original0176 trigger/ACL remain unchanged.

## Idempotency, concurrency and security

Acquire shared locks on the active user/assigned role rows, then owned preview
FOR UPDATE. A receipt with the same owner/revision/seal returns the original
applied result even after expiry or subsequent manual edits; different seal or
revision conflicts. No receipt -> require ready preview, immutable internal
identity, current role and all confirmation gates. Recompute exact seal from
stored normalized proposal via pure policy, not a new AI call.

For first application acquire tenant-owned course FOR UPDATE first, then lock
all modules/lessons and snapshot children in parent-before-child ID order,
all bound documents, approval policy/revisions and SCORM rows. Re-resolve the
complete course/source context after locks in the same transaction; stale,
published, changed source, expired or tampered preview refuses before writes.
Existing child writers need not cooperate with a new advisory lock: row locks
block updates/deletes; real immediate parent FKs plus FOR UPDATE must block
new child phantoms. This FK requirement is a mandatory actual-DB activation gate,
not something a structure-only clone or source model declaration proves.
Moving a child into the course must contend on its locked parent. Deadlock,
lock timeout, cancellation, DB failure or audit/receipt failure rolls back ALL
domain/audit/receipt writes; no blind retry or partial success.

Lock/statement limits are transaction-local3s/15s, overall apply100s; source
conversion still uses its existing90s cap. No global timeout or queue changes.
Non-super/non-BYPASS lms_app and tenant context required. Receipt RLS/FORCE RLS
enforces owner reads/inserts; purge requires exact tenant plus superadmin context.
Invoker DB trigger validates immutable parent-ready/seal/owner/time and stored
before/proposed-after digests against actual applied draft lesson, stamps DB time;
no SECURITY DEFINER/global role grants. SQL guard is defense-in-depth, not a
claim that arbitrary SQL callers execute the whole application service.

## Existing-module impact and negative space

Consumer: existing resolve_lesson_correction, foundation prepare/preview,
update_lesson, supersede_course_approvals and audit.log_action; no signatures
changed. Lesson writer marks source validation and affected quizzes needs_review
without deleting content/questions/choices. Application resets course review
to pending and clears reviewer/date/comment; approval owner supersedes active
revisions/requests/work items and revokes their credentials. Preserve immutable
approval snapshots, reviewer decisions/attempt history, source references and
current release. No published lesson, content release, enrollment, progress,
quiz attempt, notification, staff/account, provider/configuration or landing write.
No ordinary direct editor/publication behavior is globally changed or certified.

Root write scope: new correction_application.py and focused application tests;
compatible additions in correction_models.py/correction_schemas.py and
correction_router.py plus tests; additive0177 migration/static contract tests;
canonical tenant purge child statement/test; plan/index/changelog. Model registry
already imports correction_models and registers the new model. Existing lessons,
approval, audit, snapshot, resolver/provider/budget modules are read-only consumers.
UI, retention/reconciliation automation, isolated apply runtime driver and public
rollout are separate successor impacts, not silently included here.

## Retention, verification and rollout

Receipt and its parent must remain available90days from DB applied_at for replay;
no new scheduler is activated. Preview-only expiry+24h cleanup must exclude any
retained receipt parent before a correction retention runner is enabled. Canonical
exact-tenant synthetic purge removes receipt before preview and proves absence.
Downgrade refuses populated receipts; OFF flag preserves data. Old preview API
continues returning ready/stale/expired by its original contract, so clients must
read application receipt first after uncertain apply. No applied preview state.

Agreed seams: public apply/read service and HTTP confirmation, plus actual owned
DB migration/transactions/RLS/ACL/FK locks. TDD vertical success/read/replay,
wrong path/body/seal/revision, pending/failed/expired/stale/published, foreign
actor/tenant, revoked role and rollback after lesson/approval/audit/receipt failure.
Independent static migration contracts and neighboring preview/foundation/quiz/
approval/purge/AI-COURSE-01 tests. Actual isolated DEV successor must prove two
session application, existing direct write/publication/approval races, FK insert
phantoms, SQL receipt defense, one audit/receipt and preserved learner/release
fingerprints with exact cleanup/public neutrality before activation.

Ready: this interface/impact/write scope accepted before implementation. Local
Done: focused/seam/neighbor/quality + independent acceptance. Feature Done:
real FK/transaction runtime, reconciliation/retention, model semantics, before/
after UI and assembled DEV/browser then exact release gates. Stop on missing
lock/FK coverage, unlisted owner writes, weakened guards, irreversible scope or
billing expansion; root records disposition/addendum before resuming. No public
migration, production mutation or end-user release is implied by local Done.
