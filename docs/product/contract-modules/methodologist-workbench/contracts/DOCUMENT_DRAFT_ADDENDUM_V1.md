# WB-DOCUMENT-DRAFT V1

Status: Accepted for local implementation, 2026-10-04. Template V2.
Approved by: product owner, explicit "делай" following the source-grounded plan;
root approves this bounded first slice. Root/module owner: root. Reviewer:
independent read-only leaf after implementation. Preserves COMMAND-PLAN V1,
assignment contracts and AI-COURSE-01. Change control: versioned addendum;
unlisted writes, data/billing expansion and production mutation require review.

## Responsibility and interface

An active methodologist selects existing/uploaded sources, gives an instruction,
edits interpreted generation parameters, reviews an immutable source-bound plan
and confirms one existing evidence_v2 generation. A durable document plan is the
first single-course workflow context: instruction, normalized parameters,
source versions, exact admitted job and derived course/result. General multi-step
sessions, corrections, publication, assignment changes and audio are excluded.

- POST `/methodologist-workbench/interpret-document`: instruction/language to
  bounded untrusted candidate or clarification; no domain mutation.
- POST `/methodologist-workbench/document-preview`: instruction plus strict
  new-course generation parameters to preview, no job or provider generation.
- GET `/methodologist-workbench/document-plans/{id}`: owned preview or admitted
  job/result; identity is tenant AND actor, no permission from locator alone.
- POST `/methodologist-workbench/document-plans/{id}/confirm`: existing
  ConfirmationRequest; one plan/revision/fingerprint to one admitted AIJob.

Maximum five unique active verified source documents; generation guidance max
2000 characters, instruction max4000. The reviewed course_intent must be nonempty
in this command workflow: raw instruction is trace data, never silently executed
or ignored as guidance. The existing automatic `/ai/generate-course` remains
valid with empty guidance. No silent clipping. Source strategy,
mixed-language and reuse acknowledgements remain explicit existing rules.
Model never chooses IDs, recipients, approval, budget, tenant or job identity.

## Data, state, security and privacy

Workbench owns `workbench_document_plans`: tenant/actor, immutable JSON snapshot,
derived preview, fingerprint, expiry, ready/submitted state, admission time, unique job
link. AI owns job status, progress, errors and final course. A submitted plan
must not claim generation succeeded. Document owner still owns original files,
versions and lifecycle. No copies of document bodies, audio or chat history.

Ready -> submitted occurs in the SAME transaction as AI job admission, before
dispatch. Row lock serializes concurrent confirms. Replay returns the same job,
including failed/cancelled jobs; resume uses the existing job interface. No
automatic regeneration or dispatch on GET/replay. A source change, expired plan,
foreign ID, role change or fingerprint mismatch refuses execution. Error codes
are bounded; payloads/provider exceptions are not logged.

New flag `METHODOLOGIST_DOCUMENT_DRAFT_ENABLED` defaults OFF independently of the
existing workbench flag. Frontend equivalent defaults OFF. RLS/FORCE RLS,
actor ownership and runtime non-BYPASSRLS checks are mandatory. Migration is
additive; old assignment plans/endpoints remain unchanged. Plan TTL15minutes;
proposed bounded deletion uses existing metadata durations (expired ready+24h,
submitted metadata90days, only after terminal job). No scheduler activation or
public-schema migration is authorized by local implementation. Never delete
jobs, courses, learning or evidence as metadata cleanup.

## Existing-module impact and write scope

- AI router: compatible extraction of generation submission into one shared
  command, preserving existing endpoint checks/response.
- AI job_service: optional async before_commit hook joins durable caller receipt
  with job admission. Existing callers omit it; dispatch still follows commit.
- Workbench: new document schemas/model/service/router/intent; assignment router
  only includes the new router; no assignment semantics change.
- Web: new document workbench/client/tests and feature-gated page composition;
  consume canonical catalog/upload/jobs/course preview, preserve existing routes.
- DB: one additive0175 migration and contract/integration checks; no runtime
  grants expansion on existing domains or provider/billing/landing changes.
- Config, approved synthetic gates, current plan, module index, changelog and
  focused tests may change; unexpected neighbor effects stop integration.

## Verification, rollout, Ready and Done

Agreed seams: document interpretation, create/read/confirm document plan, shared
generation submission, AI admission before_commit and UI HTTP producer-consumer.
Test red/green slices, replay/expiration/source staleness, tenant/actor denial,
pre-commit failure=no dispatch, broker failure retains same job, and existing
generation/admission/assignment regressions. AI-COURSE-01 remains generation-only
with zero assignments/invitations. Canonical isolated Supabase DEV proves
migration/ownership/RLS/concurrent confirmation and normal fixture cleanup.

Ready: frozen interface/write ownership and synthetic tests. Done: focused and
seam tests, quality/build, independent review, isolated DEV and complete live DEV
document-to-draft flow. Local tests alone are LOCAL_ONLY, not release GO.
Rollback disables the new flags, preserves metadata/jobs/courses; do not drop a
populated table. Production remains unchanged until an exact authorized release.

## Controlled rollout authorization, 2026-10-05

Owner explicitly approved the requested DEV release, then production ("да, а
потом выводи в прод"). Root owns exact-SHA binding and all external mutations.
DEV: existing Supabase public174->175, Render API/worker and Vercel frontend,
unchanged Free/Hobby plans/resources/budgets; preserve permanent QA. Production
only after live DEV acceptance: exact additive CT125174->175 with signed fresh
backup/restore and independent DB readback, protected VM126 API/three workers,
native CT137 frontend, one synthetic document-to-draft smoke and guarded cleanup.
No production customer, learning, assignments, invitations, landing, DNS, access,
helper/privilege, tier, resource or spend-limit changes are authorized.

Release interfaces are additive: DEV packet V4 binds old workbench and independent
document flags to schema175; native packet V3 and build-config V2 bind both flags.
Legacy packet shapes/semantics remain unchanged. Native privileged manifest keeps
its exact eight fields; installed helper is untouched. Document ON requires old
workbench ON and native product version38+. Provider key absence means defaultOFF
only in a successfully validated inventory, never an access/error fallback.
Production backend intent/readback is owned by the higher-level root evidence
packet and a reviewed exact configuration step; protected image manifest remains
unchanged. Runtime env backups and flag-OFF rollback preserve the175 table/jobs.
Partial provider/configuration state stops for reconciliation; no blind retry.

Agreed additional release seams: strict packet validation, provider configuration
inventory/update/readback, prepare/execute/reconcile, native build attestation,
artifact inspection/pre-staging/technical receipt and bridge identity validation.
Synthetic red/green, compatibility and independent acceptance precede external use.
GO requires exact CI/image/native source parity, independent old/new identities,
worker task/queue proof, owned browser flow, source-grounded course/quiz result,
cross-tenant/actor denial, replay/no duplicate, cleanup and preserved QA evidence.
