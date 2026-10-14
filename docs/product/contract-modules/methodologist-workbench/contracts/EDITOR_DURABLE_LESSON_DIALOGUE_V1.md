# Durable selected-lesson dialogue V1

Status: Accepted by Root before implementation, 2026-10-14.
Approved by: human owner's current request for DEV, production and live acceptance;
Root accepts the bounded technical interface within that authority.
Product/root/module owner: human owner/Root/Root. Independent reviewer: Test Runner.
Extends EDITOR_CHAT_HISTORY_V1 through V1.5 and correction handoff V1.2.

## Outcome, ownership and interface

An ordinary methodologist reopens a lesson after a full reload, reads their saved
discussion, and asks a follow-up using the last admitted exchanges. One dialogue
belongs to tenant + authenticated actor + course + lesson + language. No shared
tenant chat, voice, auto-apply, provider change or automatic summarization.

Map: AIChatPanel -> existing /ai/chat optional durable_request_id -> AI lesson
dialogue owner -> existing policy/provider chat -> completed exchange -> GET
/ai/chat/lesson-history -> passive archive + bounded server-owned model context.
GET query: course_id, lesson_id, language; optional before UUID; limit fixed20.
Output: ordered exchanges {id, message, response, created_at}, has_more,
next_before, pending_request_id. Response is existing AIChatResponse.
History GET is read-only and never calls the model. Client-supplied history is
forbidden together with durable_request_id. Legacy requests remain unchanged.
Durable requests are lesson-only, methodologist-only, without audience intent.

One new table ai_lesson_dialogue_exchanges owns reservation and completed result;
it is not editor preview/receipt storage. Content is redacted before persistence.
Retention follows lesson content: retain until its lesson/course/actor/tenant is
deleted through the authorized owner. No new scheduler or shortened content TTL.
FK cascade removes dialogue with its owner; tenant purge must discover/delete it
under the canonical guarded purge boundary. Display paginates whole exchanges;
model admission remains4 whole pairs/32000 code points, no growing prompt.

## Invariants and transitions

Authenticated actor/tenant are server-owned, active role must be methodologist.
Course, module and lesson tenancy/ownership checked before read/write/provider.
ENABLE/FORCE RLS, runtime without BYPASSRLS, actor-scoped SELECT/INSERT/UPDATE;
DELETE only guarded tenant purge or FK owner deletion. No other actor's archive.
Same idempotency key + same fingerprint returns the completed response without
inference. Changed payload/key scope409. Concurrent pending scope409; pending
is durable before inference, DB context re-established after every commit.
No transaction/connection held across the provider call. State pending ->
completed or failed is terminal; failed or interrupted same key never invokes
again. Pending older10minutes is reported interrupted, not retried automatically.
Failure stores only a stable code, not exception/prompt/provider credentials.

Only completed history_eligible=true exchanges enter model context. Stored text
is untrusted USER data and passes existing refusal/redaction rules again. The
current server-loaded lesson wins. Archive proposals are displayed as unverified
text, without restored Apply/review actions, seals, receipts or execution claims.
Reload does not modify lessons or invoke generation. A fresh follow-up may use
the existing explicit source-check/consent/application path. No persistence of
unfinished client input, UI introduction, tokens or correction receipt metadata.
GET/loading errors block sending until an explicit reload succeeds; no silent
ephemeral fallback. Stale context/actor/locale/token completions remain discarded.

## Impact, verification and rollout

| Owner | Impact | Verification |
|---|---|---|
| AI schemas/router/dialogue persistence | Compatible optional interface | legacy/policy replay; request dedup, failure and context bounds |
| DB new table/registry/migration0179 | Additive ownership | empty/current upgrade, downgrade/re-upgrade, runtime ACL/FORCE RLS, actor/tenant negatives, guarded populated purge |
| AIChatPanel | Consumer | reload/reopen, paging, load error, stale completion, no restored action, course/module legacy |
| Source correction/application | None | existing handoff/unknown result/receipt tests |
| Auth/assignments/generation/worker/provider/voice | None | risk-based regressions, flags and current configuration retained |

Root write scope: named AI owners, migration0179, model registry, named tests,
DEV gate and canonical docs/plan. Bounded UI writer may own panel and panel tests
only after explicit packet. Reviewer read-only. Unlisted expansion stops editing
until Root accepts an addendum. Root owns contracts, DB, integration and release.
Errors: invalid schema422, foreign scope404, wrong active role403, pending/conflict
409, failed request503, provider502, persistence unavailable503. Never claim a
saved result after a failed commit. A lost response is reconciled by GET; no
automatic resend or fresh key to recover an unknown result.

Ready: source ownership checked, primary guard, this frozen contract.
Done: focused/contract/full candidate checks; real isolated Supabase DEV migration
and RLS/purge; exact DEV deployment, actual model + reload + follow-up; protected
production schema/API/workers/frontend release; independent identity and live
same-actor/lesson resume plus unchanged fixture content. No voice changes.
Rollback: previous application ignores additive table; retain table and records,
do not downgrade populated archive. Isolated empty downgrade must be rehearsed.
Performance: indexed scope+created_at, fixed20 display page and bounded model
history; one provider call per newly reserved request, none on reads/replay.
Observability: IDs/state/counts/hashes only, never raw dialogue in logs/evidence.
Change control: immutable V1; Root accepts versioned addendum before scope change.
