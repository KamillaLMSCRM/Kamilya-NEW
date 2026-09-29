# Recurring learning completion and source-actuality support fix

Date: 2026-09-29  
Status: RELEASE CANDIDATE VERIFIED  
Owner authorization: fix source-actuality support impersonation locally, finish
recurring learning, then release both together to DEV and production.

## Objective

An authorized methodologist can manage repeated course/program occurrences as
immutable evidence periods, inspect their history, and record a reasoned
participant deadline override without rewriting the original schedule. A
platform superadmin using tenant support mode can perform source-actuality
mutations without violating tenant-owned foreign keys, while the real operator
remains visible in the audit log.

## Scope and exclusions

In scope: source-actuality actor separation; exact program-certificate
enrollment identity; immutable recurring occurrence identity; append-only
participant deadline events; effective due-date projection; reminder
rescheduling for unsent reminders; history/override UI on `/learning-cycles`;
canonical documentation; local, isolated Supabase DEV, DEV and production
release evidence.

Excluded: SCORM recurrence, automatic publication, automatic source-driven
retraining, provider/billing changes, customer-tenant mutation, new notification
channels, commission/attestation workflow, and group/org audience redesign.

## Task graph

| ID | Owner | Dependencies | Exit gate | State |
|---|---|---|---|---|
| RC-00 | root | none | impersonated support stores nullable tenant author, real audit actor; focused tests pass | VERIFIED |
| RC-01 | root | none | program certificate selects the exact assignment enrollment; competing-occurrence regression passes | VERIFIED |
| RC-02 | root | RC-01 | additive migration adds immutable occurrence projection and append-only deadline events with RLS/FORCE RLS, upgrade/downgrade tests | VERIFIED IN ISOLATED SUPABASE DEV |
| RC-03 | backend writer/root | RC-02 | history and override public API, reminder reschedule, training-log effective deadline and cross-tenant negatives pass | VERIFIED |
| RC-04 | frontend writer/root | RC-03 contract | `/learning-cycles` exposes history, original/effective dates, reason-required override and RU/KK/EN states | VERIFIED LOCALLY |
| RC-05 | root/reviewer | RC-00..04 | focused, neighbor, full suites; quality/security/migration; isolated Supabase DEV journey and cleanup; Graphify refresh | VERIFIED |
| RC-06 | root/controllers | RC-05 | exact SHA DEV then production deployment, DB/worker/frontend readback and synthetic business smoke | AUTHORIZED, NOT STARTED |

## Evidence and stop conditions

- Graphify is navigation evidence only; decisive claims require source/tests.
- Tenant writes require server tenant context, ownership checks, RLS, FORCE RLS
  and cross-tenant negatives.
- Original target, learner, sequence, schedule, original due date and frozen
  release/version are immutable after materialization.
- Deadline override requires an active occurrence, timezone-aware new due date,
  a 20-1000 character reason, one append-only event, and an effective-date
  projection. It never changes completion history.
- Sent reminders are historical and never rewritten. Only an unsent reminder
  may be rescheduled; its idempotency identity remains unchanged.
- Stop on destructive migration, ambiguous data ownership, customer data need,
  provider cost/plan change, or a cross-module dependency outside this plan.

## Rollback

Application rollback uses the preceding production image/SHA. The additive
migration may be downgraded only when no deadline override events exist and no
new occurrence projection data would be lost; otherwise roll back application
behavior while retaining the additive schema.
