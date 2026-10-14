# Editor dialogue → source-owned correction handoff V1

Status: Accepted for bounded local implementation,2026-10-14. Template V2.
Approved by: product owner requests continued in-product assistant work;
Root approves this additive technical seam. No new DEV/production release,
provider inference/spend, schema or external mutation authorized by this document.
Product owner: repository owner. Root/module owner: Root. Independent reviewer:
Test & Evidence Runner. Predecessors: EDITOR_CHAT_HISTORY_V1..V1_5 and existing
LESSON_CORRECTION application/UI contracts remain immutable. Change control:
Root accepts versioned impact addenda before any unlisted interface/invariant.

## Outcome and directed map

An ordinary methodologist selects a saved draft text lesson, discusses a variant,
then deliberately transfers that variant to the existing source-checking panel:
editor chat → page-selected lesson guard → correction instruction staging →
explicit preview request → existing server-owned proposal/seal → human source
review/consent → existing apply/receipt/reload. Staging itself performs NO request.
Only this vertical lesson slice is added; assignment/document generation/voice,
durable conversation, model-written commands and automatic publication excluded.

## Interface, ownership and states

AIChatPanel gets optional `onReviewLessonSuggestion(lessonId,instruction):boolean`.
The sole course-editor consumer uses it for lesson-focused suggestions rather
than legacy direct PATCH. Course/module chat legacy behavior stays unchanged.
Handoff uses the selected suggestion's actual proposed text and its original
user instruction, enclosed as an explicitly unverified candidate requiring source
review. Compose at most4000 Unicode code points; oversize is refused locally,
never silently truncated. No IDs, receipts, source facts or permissions authored
by the model are trusted. No auto-apply or promise the new preview equals the
chat candidate: the correction owner independently checks/regenerates it.

LessonCorrectionPanel exposes one local `stageInstruction` handle accepting
exact lesson ID, locale and bounded nonblank instruction; returns accepted/refused.
It hides pending/unknown-result guards and owns clearing any old preview, consent,
receipt/error and URL plan locator only when a new instruction is accepted.
It then displays/focuses the instruction for explicit editing/preview initiation.
Rejected handoff preserves all panel state/URL and leaves chat open with localized
guidance. No automatic retry or provider call. Optional handle absent under existing
flags/role/impersonation/auth gates; no legacy fallback through that absence.

States: chat candidate → staged instruction → owned preview pending/ready/failed
→ existing confirmed application/receipt. Unknown preview request or application,
active request/write, manual dirty/save/load/release operation refuse staging.
Resolve the SAME request/confirmation before a new handoff. Changed actor/token/
tenant/course/lesson/locale discards stale handles through existing remount/reset;
stale handle checks mounted identity and cannot alter another context.
Staging from a ready old preview intentionally discards old local consent/locator,
not the server plan. Its existing normal TTL remains, no new cleanup policy.

Page guard requires current draft/text lesson and exact selected/chat target.
Saved-content/source/revision validation remains exclusively server-owned. Receipt
and unknown-outcome UI remain visible under the existing correction panel; history
is not an execution receipt. Source/quiz/course review resets, immutable releases,
enrollments/results and later manual-edit preservation remain unchanged.

## Existing-module impact and write ownership

| Module | Impact | Allowed change / owner |
|---|---|---|
| AIChatPanel | Compatible interface | Optional review callback, bounded untrusted candidate composition/localized labels; Root |
| Course edit page | Consumer | Current selected draft/text handoff guard and local ref; Root |
| LessonCorrectionPanel | Compatible local interface | One guarded staging handle/focus with existing lifecycle; Root |
| Correction HTTP/client/service/application | None | Existing request/4000limit/seal/idempotency/permissions unchanged |
| Chat API/history/provider | None | Existing output screening and history eligibility unchanged |
| Documents, courses/approval/quiz, assignments | None | No new writers; existing correction owner only after confirmation |
| Auth/roles/DB/RLS/workers/infra/billing/landing | None | No migration, grants, flags, runtime/provider change |

Read scope: named three UI callers, lib/lessonCorrection.ts and correction_service,
existing history/source/correction contracts and focused tests. Write scope:
the three UI files, one pure instruction composition function in existing
lessonCorrection.ts, named related/new tests, this addendum/index/continuation
plan/changelog/ledger. Root owns source/integration/governance/Git; reviewer read-only.
No new abstraction store, endpoint, provider, dependency or transaction owner.
Data: local instruction and DOM focus only; no URL/storage of instruction/text,
raw payload logging, durable history or new retention. Existing preview IDs only
remain in URL under the canonical owner.

## Error, concurrency, security and verification

Errors are local refused handoff/oversize/context unavailable; translated RU/KK/EN.
Successful staging resets consent before any new proposal and never PATCHes.
Synchronous request/write guards prevent same-tick replacement; unmount/stale
handles cannot stage. Repeated staging alone has no network or business effect.
Existing create request_key/sealed apply owns retry/idempotency/transaction policy.
No provider cost at staging; next explicit preview has existing budget/usage rules.

Executable seam tests: real chat → real correction-panel consumer without PATCH;
explicit create → exact existing seal → receipt; dirty/published/nontext/foreign/
oversize/flags/role/cross-session negatives; pending and lost preview/application
retain request/seal; stale/unmounted handle, old consent/URL cleanup, locale mismatch,
StrictMode and existing source download/lifecycle/accessibility/manual editor tests.
Focused tests first, types/lint, then one full web suite/build after integration.
No new backend owner: no migration/RLS mutation or local Docker PostgreSQL.
DEV/live provider/production remain NOT_RUN in this local slice and require an
exact existing-contour release packet/current owner release authority.

Ready: source-confirmed owner/callers, explicit negative space and Root acceptance
before implementation. Done locally: assembled seam tests plus neighbors/types/
lint/full-web/build and independent review accepted, failures retained. Rollback:
revert this frontend-only additive slice; server contracts/schema unchanged.
Stop: unlisted API/data/invariant, automatic execution, unresolved outcome discarded,
source versus graph disagreement or failing assertion needing relaxation.
Navigation: CodeGraph preflight stale; canonical sync rejected excluded4, no query
accepted. Graphify snapshot not certified; bounded named-source fallback used,
no graph efficiency or completeness claim.
