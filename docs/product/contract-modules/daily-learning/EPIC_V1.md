# Daily learning V1

Status: Accepted. Template: V2. Supersedes: None. Decision: 2026-09-30.
Product owner: workspace owner (explicit approval to implement the first cycle).
Root/module-contract owner and Approved by: Codex root, within that implementation authority.
Module owners: root for shared contracts/reporting; bounded workers for learner and action UI.
Reviewer: independent read-only worker, distinct from each writer.
Change control: stop on unlisted impact; root reviews a versioned addendum before resuming.

## Objective and evidence

Methodologists can go from a problem metric to its matching breakdown and from a
planned action to the existing confirmed assignment workflow. Learners see the
most urgent unfinished assignment, its actual deadline, why it was assigned,
and a safe continuation link. Synthetic contract, component and regression tests
prove the candidate; production readiness is a separate gate.

## Exclusions and authority

No production deployment, customer notification, customer reassignment, DB
migration, provider/billing change, CRM change, new roles or marketing claims.
Action creation remains a plan, not an automatic command. Existing assignment
and notification workflows retain their confirmation, eligibility, outbox and
delivery readback. No new reminder delivery engine is introduced in this cycle.

## Module map and active mini-specs

All three mini-specs below are V1, Accepted, approved by root; this file is their
active index. Existing data owners retain their tables, RLS and retention.

| Module | Responsibility / user contribution | Interface / inputs and outputs | Writer |
|---|---|---|---|
| RPT | Matching problem breakdown | Additive `assessment_status=failed|exhausted` on training-log list, summary and CSV; exact occurrence, unresolved quiz outcome semantics | root |
| ACT | Truthful plans and workflow launch | Validated browser-only action focus; existing GET/POST learning-actions unchanged; exact course/enrollment assignment link | action UI worker |
| LRN | Urgent next assignment and continuation | Additive student-dashboard fields `assignment_due_at`, `assignment_source`, `resume_href`; current tenant/user/occurrence, native lesson or SCORM course route | learner worker, shared deadline helper root |

Directed map: enrollment/cycle policy -> RPT and LRN read projections;
RPT -> dashboard links -> journal; learning-actions -> ACT -> existing
course-assignments workflow; LRN -> student UI -> existing course player.
There is no reverse dependency from reporting into enrollment policy.

## Mini-spec invariants and state/error contracts

- RPT: read-only; same assessment predicate for count, list, summary and CSV.
  Passed-after-failed is excluded; exhausted is per quiz, never summed across quizzes.
  Tenant/user/quiz identity and current/history rules remain intact. Invalid filter
  is rejected by API and ignored by browser parser. No pagination-only filtering.
- ACT: idle -> loading -> loaded/error; draft -> saved plan/error; navigation never
  executes a command. Saving or closing a plan does not imply email delivery.
  Browser focus never becomes an unsupported API query. Existing plan dedup and
  immutable baseline/outcome history remain unchanged. Invalid focus is ignored.
- LRN: loading -> loaded/error; only unfinished assignments compete for next.
  Overdue/earliest actual deadline precedes undated work; completed lessons do not
  imply completed enrollment (required quiz may remain). Manual deadline overrides
  eligible cycle deadline through one shared policy projection. Continuation is
  same-origin `/courses/{id}`, with native `lessonId` only; no SCORM token prefetch.
  Read queries remain bounded in query count, not per-course N+1. Auth changes
  cancel/ignore stale responses; failures expose retry and not an empty-success view.

Inputs/outputs contain only existing authenticated learner/report data; no new
logs of PII or secrets. No data writes/migrations in RPT/LRN. ACT's existing plan
POST remains role/tenant checked and idempotent according to existing policy;
new browser navigation is side-effect-free. No new concurrency adapter/provider.

## Impact matrix and negative space

| Existing module | Change | Must remain unchanged | Evidence |
|---|---|---|---|
| training-log | assessment filter; shared cycle read helper extraction | status/history/org scope, summary/list/export agreement | focused SQL/query/contract tests |
| student | additive projection and prioritization | tenant/user/current occurrence, native vs SCORM, legacy NULL progress scope | student service and UI tests |
| enrollments / learning cycles | shared read helper, assignment preselection link only | command eligibility, history, transactions, access credentials, notification delivery | existing reassignment/deadline tests; no command edits |
| learning-actions | planning labels, focus and workflow links | create has no delivery side effects, close snapshots, role checks | action component and API tests |
| course player | consumer only | release selection, quiz/SCORM launch, progress writes | existing player/regression tests |

Unlisted modules are forbidden. Error journal, release docs and changelog are
root-owned integration documentation, not new runtime dependencies.

## Verification and rollout

Module checks: focused Vitest and API pytest via canonical wrapper. Contract checks:
filter wire agreement and additive student response consumed by learner UI. Neighbor
checks: learning-actions intent invariant, deadline/reassignment/release tests.
Candidate: lint/typecheck, Python baseline, build, independent requirements/correctness/
standards/complexity review; Graphify update and directed-map comparison.
Database integration and production flow are NOT VERIFIED until run in their
approved contours. No Docker PostgreSQL. No live emails for verification.

Rollout: additive API before UI; candidate remains on feature branch pending exact
release authority. Rollback: revert this feature commit; no stored-data rollback.
Stop: identity/scope mismatch, failing hard gate, unexpected module edge, missing
approved environment or any external mutation/cost ambiguity. Root records evidence.

Ready: objective, interfaces, ownership, exclusions, impact and checks accepted.
Done: local candidate and independent review pass; durable evidence recorded;
production release remains explicitly separate, never implied by local success.
