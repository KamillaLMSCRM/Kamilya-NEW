# AI assistant continuation — text-first

Status: active; local slices verified; owner authorized DEV then production49 on2026-10-14.
Product owner: human owner, request2026-10-13 to continue the in-product assistant.
Technical/root owner: Root. Reviewer: independent Test & Evidence Runner.
Baseline: fa39b060, released native48/API47. Runtime truth remains in
PRODUCTION_READINESS; this plan is not release authorization.

## Outcome and order

Methodologist gives a textual instruction, checks the actual sources/proposal,
corrects it and explicitly confirms one server-resolved operation. The assistant
never turns conversational prose or its own previous answer into execution authority.
Voice stays deferred by the owner's earlier decision. No new model/provider,
paid resource, budget change, tenant provisioning or production mutation.

1. **Current local slice: stable editor-chat context.** AIChatPanel owns ephemeral
   messages/input and the requests for one open course/lesson/module/actor/session/
   language context. Switching context invalidates replies, errors, busy completion
   and apply notifications before paint. Abort is best-effort client cancellation;
   it does not roll back a committed PATCH or prove canceled server inference.
   One pending explicit apply per panel; unchanged API and editor callback while
   the context remains current. No storage, schema, role, worker or server-policy change.
   Root12 initial regressions RED; final17 new lifecycle cases plus accessibility5
   and correction-neighbor21 PASS. Full web152files/993tests PASS134.16s.
   Type/lint/production build67pages passed; independent source review accepted
   by Root. Current ignored receipts bind the results. DEV/production acceptance
   not performed. This local slice is complete, not the overall assistant.

2. **Current-source download in correction: implemented locally2026-10-14.**
   Accepted SOURCE_DOWNLOAD_V1 consumes authenticated document metadata and bytes,
   validates identity/MIME/size and sanitizes filenames. One lazy preparation, one
   retained Blob URL, manual download link, per-document RU/KK/EN errors, remount/
   abort-resistant/StrictMode guards and explicit current-file warning. Nothing
   embedded or executed. Metadata/citations do not expose historical byte revision:
   no equivalence or mismatch-detection claim; fragment hash is not a file hash.
   Real browser download/DEV acceptance and historical byte retrieval NOT VERIFIED.

3. **Real bounded dialogue: implemented locally2026-10-14.** EDITOR_CHAT_HISTORY
   V1/V1.1/V1.2 govern optional compatible history. Current ChatSession retains
   completed exchanges only, with the actual proposed lesson text, never IDs or
   receipts. Last4 whole exchanges/32000 code points/128000 UTF8 bytes, strict
   alternating roles and current course/focus/language envelope. All old reset
   boundaries preserved; no storage or across-close/reload persistence.
   Router passes redacted JSON history inside user data, not system/tool roles;
   existing request/output/tenant/selected-target owners remain. Refused and
   otherwise-safe denied-instruction-quoting exchanges are ineligible for replay.
   Audience owner receives no history. Previous prose is not grounding or receipt.
   Local mocked follow-up/proposal/adversarial/legacy/limits proof, not real-model
   semantic quality. One final real DEV inference/browser is a separate gate.

4. **Join dialogue to existing command owners.** Use interpretation → clarification
   → typed server preview → explicit confirmation → receipt/status/reload.
   AssignmentWorkbench/document_service/correction_application keep recipient,
   deadline, source, revision, transaction, idempotency and permission ownership.
   No direct model-written SQL, automatic publish/assignment, hidden retries or
   new parallel course-generation pipeline. Draft correction must use its owned
   revision/seal/receipt contract rather than treating legacy chat PATCH as equivalent.
   Freeze an impact matrix and executable seam tests before connecting those owners.

## Verification and closeout

Named read scope: editor chat/sole edit-page consumer, workbench module contracts,
AIChatRequest/chat handler, existing document-download owner and their focused tests.
Current write scope is expanded by accepted source/history addenda: named correction
source UI/client/tests and chat schema/router/prompt/tests, plus canonical docs.
Later command integration requires a new root-accepted impact addendum.
Pure/local mocks first; then compatible API contracts, RBAC/RLS negatives if any
server/data seam changes, existing Supabase DEV procedure, ordinary-role browser
acceptance, immutable release gates and exact owner-scoped production authority.
No local Docker PostgreSQL, policy/limiter exceptions or paid-capacity workaround.

CodeGraph readiness is stale; search and the one post-change sync reject excluded
paths4. No rejected-index queries accepted; bounded source/caller inspection used.
One accidental sync invocation from apps/web failed before opening an index;
correct root invocation recorded separately. No tool-efficiency saving claimed.

Preserve original RED and failed harness results, distinguish actual tests from
independent source review and live runtime. Remove this plan only after all owned
facts transfer to canonical docs; do not mark the whole assistant completed after
this context fix or infer any new deployment from a source checkpoint.

## Local candidate verification2026-10-14

Focused web110 PASS (47 new web cases), API64 PASS (28 new history cases) through
canonical root interpreter, type/changed-file lint and unchanged Python baseline
PASS. Full web initial1039/1 failure retained; existing journal diagnostic7 PASS
unchanged; same web source full successor with maxWorkers2 passed1040/154files
169.55s, no assertion/timeout changes. Independent review found history poison,
Root reproduced RED and repaired; V2 review accepted after source hash readback.
Source navigation audit still rejects excluded4; no rejected graph query accepted.
Next production build67pages PASS, terminal session15496 exit0. Exact source
checkpoint/readback receipt follows in ignored evidence after commit; no master/
DEV/tag promotion. No DEV/production, DB, provider resources or real inference.

## Owner-authorized release49,2026-10-14

Owner explicitly requests existing DEV live downloads and true model follow-up
including "make this version simpler", corrections, then production/live acceptance.
Root binds version49 to this package only: existing DEV API/worker/Vercel, then
VM126 API/three workers and CT137 native frontend. No migrations, flag/role/plan/
capacity changes, voice, landing/DNS/Proxmox/privilege changes or real tenant writes.
Preserve permanent QA identities/completed rows; use only bounded synthetic
course/document tests with owned cleanup or intentional test-artifact retention.

Root owns source, decisions, live browser/data fixture and documentation. Release
Runner executes immutable DEV/native/protected-backend packets; Test Runner audits
and checks evidence independently. Exact DEV ordinary-role download bytes and
context-dependent follow-up quality must pass before production, with no automatic
apply/publication/assignment. Addendum V1.3 fixes audited Russian-only prompt;
language3 RED before repair, new replay and real DEV language checks required.
Current/rollback/artifact/capacity/health and final changed-capability/live gates
remain mandatory. Earlier local-only paragraphs are historical authority boundaries.

DEV49 R2 exact0d186cd3/CI38520501058/provider/9flags accepted technically. Root
ordinary-methodologist live source preparation/download succeeded;923bytes and
SHA256374670eb… match the independent original synthetic fixture. Two-turn real
RU chat retained the previous unique label and both conflicting deadlines without
applying edits; KK/EN real replies and empty-history scope resets passed. A strict
three-sentence request produced four sentences, retained as a quality caveat rather
than a formatter guarantee. Complete marker-only replies displayed a misleading
empty label; accepted V1.5 repairs this after unchanged output/target screening.
Root75 focused tests and quality baseline pass; successor exact DEV/live and
production gates remain open. Evidence: ASSISTANT49-20261014/dev-live49-r2.json.
