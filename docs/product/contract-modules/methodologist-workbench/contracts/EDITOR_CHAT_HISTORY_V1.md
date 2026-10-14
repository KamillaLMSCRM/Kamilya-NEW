# Editor chat history V1

Status: Accepted by Root 2026-10-14 before implementation.
Approved by: Root within owner's request to continue full assistant dialogue history.
Product owner: human owner. Root/module owner: Root. Reviewer: Test & Evidence Runner.
No release, real inference, persistent storage or provider mutation authority.

## Observable outcome and public seam

After a proposal, a methodologist can ask "make that simpler" and the provider
receives the completed preceding exchange, including proposed lesson text, in
the same course/focus/language. The model still receives current server-loaded
course/focus. No prior answer is a verified source or execution receipt.

AIChatRequest compatibly adds optional history, default None. Envelope V1 has
version=1, course_id/context/target_id/language equal to the current request and
turns: 2..8 strict alternating user/assistant messages, starting user and ending
assistant. Each user text is nonblank and <=2000 code points; each assistant text
is nonblank and <=24500 (visible reply plus optional proposal, each <=12000, plus
an explicit unverified-proposal label). Entire history <=32000 code points and
<=128000 UTF-8 bytes. Unknown envelope/turn fields and system/tool roles refused.
Invalid scope, ordering, limits or blank text is schema validation failure,
before inference. Old requests without history retain the exact two-message prompt.

History owner is an ephemeral ChatSession in AIChatPanel, not DB/localStorage.
Only current-session successful completed exchanges enter history. Intro/focus
copy, network-error replies and unfinished requests never enter it. Keep latest
four whole exchanges within the shared budget; drop oldest whole pairs, never
silently clip a user sentence or proposal. No apply UUID, receipt, seal, actor,
tenant or recommendation metadata enters history. History is reset at existing
open/close/course/focus/token/actor/tenant/role/language boundaries. It does not
persist across reload or panel closing; UI must say so. Durable history is excluded.

## Safety, ownership and dependencies

Map: current editor ChatSession -> bounded untrusted envelope -> existing /chat
schema -> existing tenant/course/focus validation -> redacted JSON history inside
the existing USER data block -> existing resilient provider -> existing output
policy/selected-lesson proposal filter -> visible reply. No historical message is
injected as a system/tool/provider authority role. System prompt explicitly says
history may be forged, not grounding or execution authority; current validated
course/focus wins. Screen every history turn with existing request-refusal policy
and redact every text before inference. Refusal still observes tenant-course404.
Existing current-message refusal, output policy, selected-target filtering and
explicit manual Apply semantics remain unchanged. Prompt injection robustness is
not proven universally by pattern tests; no tool or database execution is added.

Audience recommendation remains its separate current-request aggregate owner;
history is not passed into its decision/LLM. A forced course recommendation while
lesson/module chat is selected does not enter that focus's history. Course-scoped
recommendation prose can be remembered as untrusted advice, never structured IDs
or permission to assign. Recipient selection/confirmation remain out of scope.

## Impact and verification

| Owner | Impact | Negative-space guard |
|---|---|---|
| AIChatPanel / ChatSession | Local state/interface consumer | Existing isolation/cancellation/apply/accessibility tests |
| AIChatRequest / /chat / methodology prompt | Compatible interface addition | No-history exact prompt; wrong-scope/malformed bounds; fake-provider semantic replay |
| Auth/course/focus/provider/output-policy | Existing owner consumed | Tenant404, refusal, redaction, selected-target and routing tests |
| Source download/correction/assignments/DB/workers | None | No changes to transactions, rows, queues, scopes, billing, flags or API actions |

Read/write scope: AIChatPanel.tsx, ai/schemas.py AIChat history/request only,
ai/router.py chat prompt/refusal assembly only, system_methodology_review.md,
named web/API unit tests and canonical docs/index/plan/ledger. Root owns writes;
independent reviewer read-only. No auth/DB/client/queue/provider implementation
change, migration, durable conversation records or automatic command execution.

State: current session idle -> pending -> completed pair or visible error without
a history pair; stale completion discarded. Synchronous send guard prevents an
overlapping pair. Abort cannot cancel server inference or roll back applied text.
Performance: at most8 messages/32000 code points per call; current outline/focus
limits and max_tokens remain unchanged. No extra calls or hidden retries.
Privacy: no raw text in logs/evidence/storage; synthetic unit examples only.

Definition of Ready: source seams verified, V1 limits and untrusted admission
accepted, primary guard passes. Definition of Done: schema/legacy/scope/ordering/
bounds/redaction/refusal/selected-target/provider-routing replay tests; frontend
follow-up/proposal/error/reset/whole-pair budget tests; focused download regressions;
type/lint/Python baseline/build, independent review and risk-based full web suite.
DEV real-model semantic quality and production deployment/readback NOT VERIFIED
until separately executed under their exact environment authority.
Rollback: revert compatible history consumer/schema/prompt additions; no data
migration. Change control: freeze V1; Root accepts V2 before changed limits/scope.
Stop on unlisted ownership/interface, required durable history, actual inference
or external mutation; record new accepted scope before resuming.
