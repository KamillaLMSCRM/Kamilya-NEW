# Durable document preparation dialogue V1

Status: Accepted for bounded implementation, 2026-10-15. Product owner: current
user, explicitly authorizing this package, live DEV then production acceptance.
Root/module owner: Root; independent reviewer: delegated reviewer, not its writer.
Extends DOCUMENT-DRAFT and the text-first continuation; existing V1 contracts remain
immutable. Change control: Root impact review, versioned addendum before expansion;
new authority required for billing/resources/permissions/destructive scope.

## Outcome, ownership and exclusions

An ordinary methodologist selects1–5 existing verified documents, discusses editable
course-generation parameters across messages, explicitly saves manual parameters,
reloads/reopens the same private task, reviews one source-bound plan, confirms once
and returns to the same admitted generation job/draft. Dialogue is preparation, not
general source-grounded document Q&A. No generation/publication/assignment from chat
prose. Existing document_service/submit_course_generation retain sole command and
job ownership. Voice/reserve activation/provider order/billing/customer data unchanged.

Document-dialogue module owns actor-private task/draft and immutable exchange
archive. Source versions/hashes/index revisions/language are immutable task scope;
changed sources require a new task. History is untrusted, never evidence/authority.
Task draft is editable with optimistic revision; previews/receipts remain separate.
Retention until normal actor/tenant purge, cascade via exact parent FKs. No scheduler,
bulk deletion, new raw-document archive, localStorage credential/prose persistence.
Bounded100 tasks/actor,40 exchanges/task, latest4 completed user instructions for
model recall (<=16000 characters),4000 per instruction. Recent-task list paginates20.

## Interface (prefix /api/v1/methodologist-workbench)

- POST /document-dialogues: {task_id UUID, document_ids UUID[1..5] unique,
  language ru|kk|en, draft}; same UUID+creation fingerprint replays, conflict409.
- GET /document-dialogues?before=UUID: {tasks:[{id,title,updated_at,plan_id}],
  has_more,next_before}; owner-scoped cursor, no inference.
- GET /document-dialogues/{id}: TaskResponse, no inference or generation.
- PATCH /document-dialogues/{id}: {expected_revision,draft}; save-only; pending or
  submitted/unknown plan blocks, stale revision409. Saved draft invalidates old plan.
- POST /document-dialogues/{id}/messages: {request_id UUID,expected_revision,
  instruction}; persisted reservation before provider, exact replay no reinference;
  pending409/failed503, never silently retry.30s overall/8s transport attempts.
- POST /document-dialogues/{id}/preview: {expected_revision}; consumes saved draft
  and existing create_document_preview, atomic plan link. Same ready plan replays;
  explicit expired preview request may replace expired ready plan, never submitted
  or unknown outcomes. Existing document-plans/{id}/confirm and GET own execution.

Draft = {instruction:string<=4000 (empty allowed), candidate:DocumentCandidate,
language_confirmed:boolean,reuse_reason:existing enum|null}. Candidate language must
match task language. Source/language change starts a new task, never mixes recall.
TaskResponse = {id,revision,language,sources:DocumentSource[],draft,plan_id UUID|null,
source_stale:boolean,pending_request_id UUID|null,interrupted_request_id UUID|null,
exchanges:[{id,instruction,state:pending|completed|failed,response:existing
DocumentInterpretation|null,error_code:string|null,created_at}],created_at,updated_at}.
Responses are typed/strict, bounded and no-store. Source titles are metadata only.
Model receives current editable candidate, bounded prior user instructions and
source titles as untrusted JSON. No model-selected documents, IDs, authority or jobs.

## State, persistence, concurrency and errors

New additive0181 owns workbench_document_dialogues/tasks and
workbench_document_dialogue_exchanges, both tenant_id+actor_id, FORCE RLS/non-BYPASS,
active-methodologist admission, context-required immutable scope/terminal guards.
Foreign tenant/actor/role denied; actor/tenant cascade ordering must be verified.
Commit/rollback loses LOCAL security context: rebind before every owner transaction.
No DB connection/row lock across inference. Reauthorize active actor/source relation
and lock current relation before terminal persist. Deleted/moved source fails closed;
same-owner changed source metadata shows stale and cannot execute new preparation.
Two-minute pending lease; GET projects interrupted without mutation; explicit new
message terminally reclaims old pending request, late result cannot overwrite it.
Provider failure/cancellation leaves explicit failed/interrupted state, no auto resend.
Message reservation increments task revision, terminal completion increments again;
pending task blocks draft/preview/more messages. Request UUID/fingerprint immutable.

Existing DocumentSnapshot receives optional dialogue_task_id/dialogue_revision,
internally assigned only. Legacy fingerprints omit ONLY absent new metadata and
retain all previous nullable fields/bytes. New task preview links same revision;
confirm validates current task/plan/revision under lock before existing submission.
Saving/changing task makes an older linked preview409; submitted receipt replay
remains GET/replay-safe. Plan ID is retained as opaque recovery locator even if
normal retention removes its row: unknown plan blocks, user starts a new task.
Never hide a lost confirm response by enabling another generation. Frontend preserves
opaque task/request/plan locators and has an explicit read-recovery action.

## Impact/write matrix and negative space

Root: this contract/index/continuation/canonical docs; new dialogue schemas/models/
service and0181; document_intent additive internal context/transport deadline;
document_router compatible routes; document_service optional snapshot metadata and
confirm freshness guard; tests and isolated DEV gate. Existing lesson/assignment
archives, course generator/business gates, quotas, queues and routing unchanged.
Delegated frontend writer: DocumentWorkbench.tsx, new documentDialogue.ts transport
and focused document dialogue UI tests only. Preserve upload/index epochs/catalog,
legacy plan deep links, RU/KK/EN, single pending action, manual canonical screens.
Root owns shared metadata, migration/registration/purge/release integration if needed.
No platform authentication redesign, another executor or global chat framework.

## Verification / Ready / Done / rollout

Ready: exact current source/instructions; accepted ownership/interface; independent
source review; graph unavailable recorded (stale/excluded4), bounded source fallback.
Focused tests through public seams: create/save/reload, structured history recall,
unknown/pending/interrupted/replay/conflicting key, stale revision/old preview,
source change/move during wait, cancellation/refund/context rebind, cross-owner/
tenant/role, frozen terminal rows, legacy fingerprints and generation single-job.
Actual isolated Supabase DEV migration empty/populated upgrade, downgrade-empty/
populated refusal, FORCE RLS/ACL/runtime non-BYPASS, owner writes/replay/negatives,
owned cleanup and public neutrality; no local Docker PostgreSQL.
Then full risk-based API/web/types/quality/CI, actual DEV task3messages/manual save/
two reloads/close+reopen/explicitconfirm1/same job and draft/course result; production
same on permanent synthetic QA only. Record timing/calls/old learning preservation.
Signed current-schema backup/restore, protected backend/schema and native frontend
release, exact public/private/allworker identities/flags/OFF readback and monitoring.
Rollback application-compatible additive schema; do not drop populated history.
Stop on missing source/ambiguous state/isolation/cleanup/rollback/authority/billing
failure. Done only with exact deployed identities and documented actual user outcome.
