# Manager attention contour — EPIC V1

Status: Accepted for incremental local implementation, not production release.
Epic ID: KML-MANAGER-ATTENTION. Document V1; template V2; supersedes none.
Decision date: 2026-09-05. Product owner: repository owner, direction
«план и реализация» / «делай». Root: Astra, contracts/integration/acceptance.
Change control: proposal → impact review → versioned addendum → implementation.

## Outcome and success evidence

A manager sees who needs attention, the real deadline, and a traceable action
and outcome, without maintaining a parallel spreadsheet. Course completion is
not proof of competence or legal compliance.

Delivery chain: existing enrollment/cycle → R1 deadline reporting → R2 durable
reminder → R3 manager action → R4 measured learning result → R5 onboarding view.
This is a directed dependency map, not permission to ship all stages together.

## Active module index and ownership

| Module | Active contract | Data / writer | State |
|---|---|---|---|
| R1 deadline reporting | `modules/training-deadline-read-model_V1.md` + `modules/training-deadline-read-model_V1_review-addendum.md` | no new table; root backend, Terra UI/tests | local + Supabase DEV accepted; not released |
| R2 recurring reminders | `modules/recurring-reminder-delivery_V1.md` | new outbox planned; root schema/seams | draft delivery/migration packet |
| R3–R5 | dated implementation plan | no new ownership accepted | planned |
| R6 competencies | no accepted contract | none | deferred |

Interfaces: R1 adds compatible fields/filter to existing training-log API/CSV.
R2 must use its own occurrence-bound outbox; initial assignment delivery remains
unchanged. See the R2 mini-spec for the proposed command boundaries.

## Roles and allocation

Root owns shared files, DB/infra, migrations, quality gates and release readback.
Product owner decides activation, retention changes, spend and production scope.
Luna/medium independently reviews bounded source; Terra/medium implements owned
UI and synthetic tests in serialized packets. Both are leaf agents, English-only,
no external access, secrets, Git mutation or neighboring edits. Maximum two.
Root reviews artifacts directly; agent `READY` is not acceptance.

## Impact and negative space

| Module | R1 impact | Must remain unchanged | Check |
|---|---|---|---|
| training_log | additive API/CSV/deadline policy | completion/evidence ownership | unit + reporting integration |
| learning_cycles / learning_paths | read-only joins | frozen deadlines, assignments, scheduler | terminal/provenance tests |
| web training log + locales | filter, date, badge, count | authentication and roles | RTL + typecheck |
| enrollments / notifications / email | none in R1 | existing outboxes, sends, provider config | no changed runtime files |
| operations | fixed DEV verification entrypoint | no local DB, migrations or provider writes | identity + rollback checks |

Unlisted modules require an impact addendum. Preserve unrelated dirty work.
R1 needs no migration; R2 expand-only migration precedes disabled application
code. Never backfill sending or drop delivery history as part of rollback.

## Critical journeys and states

| Journey | Action | Required evidence |
|---|---|---|
| CJ1 | manager filters overdue cycles and exports | row/count/CSV agree on immutable deadline |
| CJ2 | occurrence cancelled/skipped or enrollment completed | no false overdue; legacy missing data not reassuring |
| CJ3 | tenant A supplies tenant B identity | no row/count leak under actual `lms_app` |
| CJ4, R2 | opt in, materialize, delay worker, recover | one ledger item; eligible delivery or visible suppression |

R1 derives not_applicable / active / overdue / completed_on_time / completed_late
without writing transitions. R2 states and recovery are specified separately.

## Verification and release boundary

Focused policy/CSV and RTL checks; existing Python baseline and frontend
typecheck; canonical Supabase DEV reporting tests with rollback and actual
runtime role; Graphify AST update and source-confirmed dependency comparison.
Production Done additionally requires exact commit/remote/provider revision,
approved release gates and real manager-flow readback. Local and DEV acceptance
must remain distinguishable from production Done.

Stop on tenant leak, row/count disagreement, unplanned module impact, failing
cleanup, billing uncertainty, or missing exact external authority. Scope review
and source checks may continue while deployment is stopped.

Ready: versioned seams, owners, exclusions and tests named. Done: all applicable
journeys and release evidence pass; see dated plan for observed test outcomes.
