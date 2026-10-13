# AI assistant continuation — text-first

Status: active, local first slice verified; no new deployment.
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

2. **Source navigation in correction.** Current LessonCorrectionPanel still renders
   citation document UUID/locator/evidence hash, not an original-file opener.
   Consume the existing authenticated `/v1/documents/{id}/download` owner,
   preserving tenant checks and deleted/unavailable states. Before implementation,
   accept an impact addendum covering current file versus cited revision, MIME/name,
   cleanup of Blob URLs, abort/session guards and source-version mismatch. Fragment
   evidence hash is not a whole-file hash and does not prove original-byte equivalence.
   Never fabricate a quoted excerpt or assume that the latest file is the cited revision.

3. **Real bounded dialogue, not a visual-only history.** Current AIChatRequest has
   only `message`/course/context/target/language/intent. The router sends current
   outline/focus and the latest user message; it does not send prior UI turns.
   Define a versioned conversation-context contract before backend/client edits:
   actor/tenant/course/source binding, bounded turns/bytes, retention or explicit
   ephemeral state, reset behavior, redaction and untrusted-history admission.
   Previous assistant prose is neither a verified fact nor a tool receipt.
   Test "make that simpler" after a proposal, topic changes and adversarial history;
   old clients without history retain current behavior. Replay recorded provider
   outputs first, one final bounded real DEV inference only after local gates.

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
Current write scope: AIChatPanel, lifecycle test, changelog/error journal/backlog
and this temporary plan. Later slices require explicit root-accepted scope addenda.
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
