# Free-text assignment intent addendum V1

Status: Accepted for bounded implementation, 2026-10-04.
Extends WORKBENCH V1 and ASSIGNMENT_EXECUTION_ADDENDUM_V1; predecessors preserved.
Approved by: root under the owner's current "Делай" for the stepwise AI-driven plan.
Root/module owner: root. Product owner: human owner. Reviewer: independent leaf
and Test & Evidence Runner on a frozen packet. Release remains a separate gate.

## Responsibility, contribution and exclusions

An ordinary methodologist can describe one course-to-department assignment in
natural language, inspect/edit the extracted fields, then request the existing
server-resolved preview and explicitly confirm it. Interpretation never assigns,
publishes, creates recipients, sends mail or confirms a plan. Speech, QR, document
generation/editing, new models/resources, migrations and billing settings excluded.

## Interface and state

POST `/methodologist-workbench/interpret-assignment`: instruction1..4000,
timezone_name, notify/include_descendants defaultsfalse, optional previous_plan_id.
Return `interpreted` with an editable strict candidate, or existing
`clarification_needed` with safe code/empty resource choices. No model prose/IDs.
Candidate: course_query/department_query nonblank strings1..300, due_date ISO,
due_time HH:MM:SS (explicit time or23:59:59), notify/include_descendants booleans.
Timezone always comes from the validated UI/request, never the model.
Optional previous_plan_id must be owned by current tenant/actor, unexpired and
ready, before admission/provider resolution; model context contains only its
course/department names, local deadline and scope options, no IDs/recipient PII.
No raw instruction or provider response is persisted/logged by this module.

POST existing `/assignment-preview` extends compatibly with optional `candidate`
of this shape. Without candidate the exact parser remains unchanged and free.
With candidate, treat every field as untrusted: calendar/time/timezone/future
validation, exact tenant-local published-course and active-department resolution,
selected duplicate IDs validation, existing audience snapshot/expiry/locks all
remain server-owned. This endpoint never calls the LLM. Every edit/reinterpretation
clears the old confirmation and creates a new plan; confirm/reload unchanged.

Raw provider response has action `assignment_preview|clarification|unsupported`,
nullable course_query/department_query/due_date/due_time/notify/include_descendants,
extra fields forbidden. Missing/ambiguous/relative date, compound/unsupported
action -> clarification, never guessed execution. Negative preview requests such
as "пока не назначай" are compatible with preview only; cancellation/no-assignment
without a requested preview is unsupported. Provider failure/invalid JSON -> safe
clarification, no semantic retry or deterministic guessed assignment.

## Dependencies, costs, performance and ownership

Map: UI -> interpret route -> existing authorized AI admission/provider routing ->
pure candidate validator -> editable UI -> existing preview resolver -> existing
plan/confirmation. Existing route/order/tenant override are used unchanged;
no provider configuration write. Max input4000, output1200tokens, outer timeout30s,
transport retries0 per provider; transport failover only, no validation-triggered
provider failover or syntax/semantic repair call. Actual provider
transport totals/price are not claimed from estimated budget reservations.
No new business table/queue/scheduler/retention. Interpretation may write existing
AI usage through the canonical admission contract, not a course/trial generation.
Repeated explicit interpretation is a new billed parse; no automatic replay/retry.
The historical owner$1 test ceiling is not reinstated. Existing quotas/budgets
must not be bypassed; exact admission binding is root-reviewed before integration.

Root admission decision: reuse check_and_charge_llm_budget with operation
assignment_intent_parse and estimate1cent (reservation, not billed price), commit
before provider, canonical refund on controlled failure. No course/trial quota.
Source review found existing budget first-insert bypass and zero-budget fallback;
root accepts narrow interface impact in ai/budget.py: honor explicit zero and
first-row budget predicate, unchanged defaults/ledger/schema/generation callers.
Dedicated interpretation rate6/minute,60/hour,burst3, fail closed if limiter
unavailable, through existing principal middleware. No external spend limit change.
Shared writes permitted: ai/budget.py and core/rate_limit.py plus focused tests;
no provider/client/routing/auth invariant changes. These shared deltas require
neighbor budget/rate-limit regressions and independent review before release.

## Impact, privacy and negative space

WORKBENCH interface extension owns new intent module, application/router/schema
integration, editable frontend and tests. AI routing/client/budget admission are
consumed, not reconfigured. Existing auth/RBAC/RLS, active-role methodologist gate,
impersonation denial, raw exact commands, canonical confirm/reload, mail/outbox,
course versions/history, provider order/monthly limits and public pages unchanged.
No broad tenant catalogue/employee names/email goes to model; only request and
optional owned plan's minimum semantic fields. Arbitrary extra authority rejected.
Input UI warns against secrets/PII; operational metrics only safe reason codes.

## Verification, scope, Ready/Done and stop conditions

Read scope: workbench contracts/source/tests; existing AI admission/router/client,
rate limit, usage and plan policy. Write scope: workbench owned source/tests and
frontend library/panel/tests; root canonical plan/module index/changelog/evidence.
Any required shared AI/rate policy change needs a root-approved impact addendum
before editing that module. No secrets/external actions for leaf workers.
Pure synthetic JSON replay + invalid/extra authority/relative dates/errors;
HTTP auth/feature/impersonation/previous-owner gates before provider; admission
denial before resolution; candidate->preview->confirm reuses existing contract;
UI edited input/late response/session/reset/no auto-confirm + RU/KK/EN copy;
canonical focused module and neighbor tests/quality/type checks, independent
frozen review. Live DEV/provider/browser and production release/readback are
distinct subsequent gates, not proven by mocks. No DB migration in this slice.
Ready: interfaces/scopes frozen and exact admission seam source-confirmed.
Done local: implemented chain, proportionate regressions and independent review.
Stop on missing policy, unowned previous plan, unsafe provider output, unexpected
shared changes, untested isolation, recurring access failure or release/billing
authority expansion. Rollback retains old exact parser; no plan/history erasure.

## Owned Supabase DEV verification extension

Root may extend existing workbench_assignment_dev_gate with explicit
--intent-profile, invoking new workbench_intent_dev_checks only in its already
validated random workbench_<12hex> schema. Clone tenant_llm_usage definitions
without rows; bind source0039/0042 FORCE-RLS tenant policy and an owned invoker
set_current_tenant helper. Use synthetic existing gate actors/settings only.
Every transaction sets owned-only search_path, including after admission commit;
no public fallthrough or public DDL/DML. Test first-row zero budget denial,
reservation exhaustion/concurrency, controlled-failure refund after commit,
ordinary owned candidate->preview, previous actor/tenant denial before provider.
Provider is a local synthetic stub, zero paid calls/email/tasks. Existing exact
schema cleanup/absence and public snapshot neutrality remain mandatory.
Write scope extends only these two ops scripts and focused gate guard tests;
no public migration, provider deployment or permanent QA reset implied.
