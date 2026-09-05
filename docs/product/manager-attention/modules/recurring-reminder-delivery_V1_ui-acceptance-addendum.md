# R2a UI and assembled-chain acceptance addendum V1

Status: Accepted by root, 2026-09-05, under owner's explicit continuation.
Extends (does not replace): recurring-reminder-delivery_V1.md and its
implementation-addendum. Product owner: workspace owner; root/module integration
owner: Astra; UI owner: Terra; independent reviewer: Luna.
Change control: root reviews bounded implementation changes; owner approves
business scope, production activation and real-recipient delivery.

## Outcome and interface

Methodologist can edit reminder opt-in and lead (integer 1–30 days) on an existing
recurring rule, and explicitly load its recent safe delivery statuses. Existing
assignments screen is canonical; no new route or auth scheme. Use current
GET /v1/learning-cycles, PATCH /{id} with only the two reminder fields, and
GET /{id}/reminders. No UI invocation of worker/send/resend or global enablement.
State: initial saved rule -> local draft -> pending -> persisted rule or visible
error retaining draft. History: not requested -> loading -> empty/data/error;
errors never masquerade as empty results. Superseded requests cannot display
another rule's results. Disable duplicate mutations and validate before PATCH.

Clarify: opt-in is configuration, not proof of a sent email; global rollout may
still be off. Lead changes affect future materializations, not frozen queued dates.
Disabling opt-in suppresses pending eligibility; do not promise cancellation of
an already reserved provider request. Historical cycles are not backfilled.
Program rules must not send cadence/due fields in this PATCH.

## Ownership, impact and exclusions

Learning cycles owns rule settings; reminder delivery owns outbox, tenant-scoped
safe status reads and delivery state. UI owns only unsaved draft/display state.
Existing RLS, retention, idempotency, provider and global-off policy unchanged.
UI consumes these interfaces; no migration/ownership change planned.
Root may add integration harness/tests and fix confirmed seam defects through
an additional accepted addendum. No arbitrary schema rewriting in product code.

Terra write scope: apps/web/src/features/course-assignments/** and new focused
apps/web/tests/recurringReminders.test.tsx. Root owns all other paths and docs.
Read scope: related UI/tests, backend learning_cycles schemas/router and reminder
migration return columns; applicable instructions and named skills.
Negative space: existing assign/access/activate flows, active-role guard, program
cadence, initial assignment email, provider config, shared DEV/public unchanged.
No new packages, polling, scheduler, SMTP switch, live email or production writes.

## Verification and stop conditions

Focused RTL: default off, 1/30 boundaries and invalid values, reminder-only PATCH,
saved response, failed save preserves draft, status loading/empty/error/states,
duplicate-click guard, request isolation and existing assignment regression.
Root typechecks and reviews UI. Backend acceptance must use actual API handlers,
materialization/store/worker interfaces, durable DB state and synthetic transport;
label any test adapter, broker substitute or partial dependency schema explicitly.
Only isolated Supabase DEV schema with exact cleanup; full legacy migration chain
must not be applied to shared public as a workaround. If safe full-application
isolation is unavailable, report the precise missing gate, not a fabricated PASS.

Ready: fixed interface and disjoint ownership above. Done: reviewed UI and passed
focused/type checks, assembled-chain evidence with limits and no cleanup residue.
Stop on unplanned cross-module changes, untestable isolation, or new authority.
Disable/rollback: default global-off preserved; UI changes do not activate delivery.
