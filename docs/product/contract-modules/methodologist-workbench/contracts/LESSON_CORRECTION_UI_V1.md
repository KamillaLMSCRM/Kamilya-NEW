# Lesson correction UI V1

Accepted 2026-10-05 before implementation. Successor of correction preview and
application contracts; those transaction, ownership, quality and release gates
remain unchanged. Isolated application DEV E passed24 checks; this is not public
activation, UI acceptance or semantic quality proof.

## Public seam and compatible API addition

`CorrectionPreviewResponse` adds required `revision: Revision`, copied from the
validated immutable snapshot in create, ready reload, pending and failed responses.
The client never assumes revision1 or derives it from an editable field. No schema
migration, new provider call or change to confirmation/receipt persistence.
Pending/failed snapshots remain readable; ready reload keeps live revalidation.

New client `apps/web/src/lib/lessonCorrection.ts` uses existing authenticated `api`:

- `createLessonCorrection({request_key,lesson_id,instruction,locale},signal?)`
  POST `/v1/methodologist-workbench/lesson-correction-previews`.
- `loadLessonCorrection(planId,signal?)` GET preview.
- `applyLessonCorrection({plan_id,revision,fingerprint},signal?)` POST exact
  plan `/apply`; response identity, revision and fingerprint must match that seal.
- `loadLessonCorrectionApplication(planId,signal?)` GET `/application`; only a
  definite404 returns null. Network/401/403/malformed payloads are not absence.

Validate UUIDs, positive safe integer revision, SHA256, timezone-aware timestamps,
bounded instruction1..4000/nonblank, localeRU/KK/EN, preview discriminants, ready
fingerprint/before_content/proposal and1..64 bounded citations with documentUUID,
locator1..120 and evidenceSHA. Text content max64000 per server `Text`. Validate returned
plan identity for GET and sealed apply, returned lesson for create. Reject malformed
responses rather than displaying success. Provenance is structured metadata from
server, never an accuracy certificate. Exact field limits follow server contract.
No credentials, source bytes, prompt or proposal in localStorage/logs.

## Panel and authoring integration

New `LessonCorrectionPanel` embedded only for a selected saved native-text lesson
in draft course editor. Existing ordinary methodologist session, non-impersonation,
`NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED=true` and new
`NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED=true` required; absent flags
hide entry, server flags remain independent OFF defaults. No release flag change.
This increment does not expose correction as the old chat's implicit write tool.

Props identify course/lesson/title/saved content, editor dirty/busy state and callback
for a verified receipt. Remount on session/selected lesson change, abort owned GET
and preview requests, suppress late responses using operation epoch and current
identity. Language comes from language store; changing UI language invalidates an
unapplied preview. Never show a previous session's proposal or receipt.

Unsaved title/content or an in-flight manual save prevents generation/application
and explicitly asks to save or discard first. Changes after generation invalidate
confirmation. Before-content comes from server, not the editable buffer. Compare
before/after in bounded scrollable plain-text panes; preserve paragraphs/whitespace,
never inject raw HTML. Show source document identity/locator (not fabricated quoted
excerpts), validity deadline and review consequences. Provider policy/deterministic
checks do not prove factual correctness; methodologist must review sources and
quiz. Application requires an explicit button and reviewed checkbox; old previews
are not applied after instruction/locale/context edits, expiry or dirty editor.

Application disables further manual/editor mutations and lesson navigation for the
owned operation where possible; session change/unmount still suppress late updates.
Unknown write outcome or typed busy409 performs GET application first. If no receipt,
retain the exact seal and display explicit check-result / retry-this-confirmed-plan
actions, never retry POST automatically. Other conflicts require fresh preview.
Reconciliation GET failure remains uncertain; missing receipt is not proof of a
failed write. No new provider call as recovery. Pending preview shows factual pending
state and explicit GET refresh, never repeated create with a new request key blindly.

Only opaque `correction_plan` UUID is stored in the editor URL, preserving unrelated
query/hash. On restoration, GET receipt first (historical receipt valid even after
preview expiry/manual edits), otherwise GET preview. Restoring a receipt does not
replace current lesson content. A plan for another selected lesson is refused.
Instruction is not returned by the current API; do not pretend restored instruction
exists. A new local instruction edit invalidates restored preview. New preview
replaces only this opaque pointer, not unrelated document/assignment URL state.

After fresh successful application, parent updates local saved/content view only
when lesson/session and original saved/clean buffer are still current, and marks
course review pending. Otherwise preserve buffer and offer explicit reload after
save/discard. Never overwrite a later manual edit, including after lost-ack recovery.
Historical receipt restoration never causes an editor write. No automatic publish,
assignment, quiz replacement, notification or learner progress mutation.

RU/KK/EN copy uses existing language-store pattern, explicit labels, status/alert
regions and accessible source details. Mobile comparison stacks without page-width
overflow. Help states exact scope: one saved draft lesson, evidence-backed proposal,
explicit application, source/quiz review and renewed course approval required.

## Verification and remaining gates

Public service create/reload/pending/failed revision regression; typed transport
behavioral tests; panel before/after/explicit consent/dirty invalidation/expiry,
malformed or wrong identity, pending recovery, busy/lost-ack receipt-first/no blind
POST, historical restore, StrictMode/abort/session/locale/lesson late-response tests;
parent integration must preserve manual changes. Existing type/lint/build checks
and independent frozen Test Runner acceptance. Keep local unit, source, isolated DB,
assembled DEV browser, real provider semantic and production evidence separate.

Public schema migrations, deployment flags, retention/reconciliation and real model
quality gates remain separate. No production release on this UI contract alone.
