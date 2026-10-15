# Assignment dialogue V1

Status: Accepted for implementation, 2026-10-15.
Template: V2. Extends LLM_ASSIGNMENT_INTENT_ADDENDUM_V3 and assignment execution V1;
accepted predecessors remain immutable. Root/module owner: Root. Product owner:
human owner, current request authorizing DEV then production/live synthetic acceptance.
Reviewer: independent Test & Evidence Runner. Approved by Root within that request.
Change control: unexpected impact stops editing; Root accepts a versioned addendum.

## Responsibility and user outcome

One ordinary methodologist discusses one course-to-department assignment, corrects
it, inspects authoritative recipients/deadline/options, explicitly confirms, and
can reopen the same result after reload. Existing assignment owner remains sole
writer of enrollments/receipts. Dialogue is untrusted input, never execution authority.
Non-responsibilities: new audience filters (e.g. "newcomers"), recurring rules,
voice, course generation/publication, notification delivery, account creation,
provider/model/billing/resource changes, global chat routing and lesson archive.
Unsupported filters/compound commands require clarification, not broadened recipients.

## Directed map / external interface / inputs and outputs

AssignmentWorkbench -> interpret-assignment -> existing provider/admission ->
editable candidate -> assignment-preview -> existing owned plan -> human confirm
-> existing enrollment owner/receipt -> GET same plan/result navigation.

Compatible request extension: AssignmentInterpretRequest optionally accepts
instruction_history: tuple of at most4 nonblank strings, each at most2000 chars.
Total history at most6000 chars. Current instruction remains1..4000. No assistant
prose, IDs or prior results are accepted as history. Default empty preserves old
requests. Prior user instructions are JSON USER data, not system messages or facts.
Latest instruction overrides older conflicting details; unresolved omissions and
unsupported audience qualifiers produce clarification. Existing owned previous
plan remains authoritative contextual candidate; history supplies missing user
intent only. Current relative date rejection remains; no guessed year/timezone.
No history storage or new schema. Ordinary admission/limits/no hidden retry unchanged.

Compatible receipt enrichment: optional course_id from the existing frozen preview
is returned on new confirmation, GET/replay (including legacy stored receipts),
without rewriting stored historical receipts. It enables canonical /assignments
course navigation after reload; no recipient credentials/PIN/links are exposed.
Receipt fields remain stable; old clients and receipts continue to work.

## Ownership / privacy / retention

Local visible dialogue and bounded user history: mounted workspace, keyed by
actor/tenant/role/token/language. No storage, no logs; new command/context reset
clears it. Only explicitly sent user instructions go to existing tenant provider.
UI warns against secrets/PII and explains that pre-plan conversation is temporary.
Server assignment plans/receipts keep their existing tenant+actor RLS/FORCE RLS,
15min expiry /24h expired-plan cleanup /90day receipt policy. No retention change.
AI usage keeps its existing admission owner. No new tables or authorized writers.

## States, ordering, errors and concurrency

empty -> interpretation -> candidate OR clarification -> editable correction ->
preview_ready -> explicit confirm -> succeeded. Missing details can be supplied
in a next turn; there is no auto-confirm. Any edit invalidates the prior preview.
Same-ID reload is GET only, never fresh inference/confirmation. Text/history and
request continuations cannot cross authenticated or language contexts. Synchronous
request ownership prevents double send/confirm; abort is not server rollback.
Confirmation response lost -> unresolved same plan; preserve locator/fingerprint,
block replacement/editing; explicit same-ID read or same-ID confirm recovery only.
Read ready does not prove the earlier confirm was cancelled; do not unlock new
assignment from that observation. Same-ID confirm uses existing row lock/idempotency.
Errors show safe existing codes; never raw provider exceptions or fake success.

## Impact, scope and negative space

| Owner | Impact | Write scope | Required regression |
|---|---|---|---|
| Intent module | compatible history request/prompt | assignment_schemas.py, intent_application.py, natural_assignment_intent.py | bounded untrusted history, authority rejection, one call, old requests |
| Assignment owner | computed receipt course metadata only | assignment_service.py | unchanged atomicity/replay, legacy receipt, owned read |
| Web workbench | dialogue/context/recovery/result link | AssignmentWorkbench.tsx, assignmentDialogue.ts, methodologistWorkbench.ts and direct tests | stale/late/session/locale/double-send/unknown confirm/reload |
| Root docs/release | contract/index/plan/ledger/error/changelog/version | existing canonical owners and metadata | exact candidate gates/readback |

Auth, RLS, enrollment policy, audience membership, notification/outbox, provider
routing/rate/budget, schema0179, workers/queues, customer records, manual assignment,
document/correction/lesson chat and public pages must not change. Interpret/preview
do not assign. Existing flags remain unchanged. No new dependencies.

## Observability / performance / adapters

Safe evidence: exact SHA, opaque plan/fixture IDs, result counts, request counts,
source hashes, durations and codes. No credentials, raw contact data or auth traces.
At most one existing interpretation call per explicit send; history budget6000
chars, output1200 tokens/timeout30s/provider retries0 unchanged. No automatic model
repair. Existing mocked API/provider adapters and owned Supabase isolation are used.

## Verification / implementation packet / stop conditions

Root owns shared schemas/application/assignment/UI integration and release.
Disjoint pure helper writer may own assignmentDialogue.ts and its test only.
Read scope: named modules/contracts/tests and canonical runtime runbooks.
Before implementation: focused RED for missing-detail follow-up, bounded/history
transport, stale context, result recovery and legacy receipt enrichment. Then
focused API/web/neighbor and executable transport contracts; canonical Python
quality/type/lint; isolated Supabase existing ownership/replay/atomicity gates;
one full web candidate suite/build and exact CI. Graph candidates source-confirmed;
CodeGraph excluded4 rejected, Graphify static/partial; bounded source fallback.
DEV real provider: incomplete request -> exact follow-up -> candidate -> preview
-> correction -> new preview -> confirm -> same receipt reload, recipient visibility.
Production repeats only in permanent synthetic QA, notify=false, dedicated new
synthetic fixture if needed through ordinary APIs, no completed learning/customer
edits. Exact fixture identity/retention and absence of mail verified/documented.
Stop on authority/billing ambiguity, new data owner, unlisted policy/module,
untested isolation, repeated access failure, or need to weaken tests.

## Rollout / rollback / Ready / Done

No migration; schema0179 stays. Compatible backend first, frontend second, existing
DEV resources then protected/native production exact-SHA gates. Rollback51 keeps
plans/receipts and ignores additive fields; no deletion/downgrade. Ready: this
contract/source seams accepted and tests named. Done: integrated tests, independent
review, real DEV and production journey/reload/no-duplicate evidence, synthetic
state safely retained or scoped cleaned, canonical docs updated. Wider quality,
voice and automatic execution remain unclaimed.
