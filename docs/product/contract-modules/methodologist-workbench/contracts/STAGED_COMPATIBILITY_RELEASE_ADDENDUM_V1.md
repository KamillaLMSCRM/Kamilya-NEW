# Staged compatibility release addendum V1

Status: Accepted by root,2026-10-02, BEFORE staged implementation. Owner request:
continue the agreed plan and release to production. Existing impact/invariants
remain authoritative; no billing, new resources, broad cleanup or voice authority.

## Scope and verified existing seam

Unpublished public migrations0169–0172 and compatible application binary. Existing
protected production workflow/release_plane exact migration mode accepts an interim
revision; installed Compose overrides Docker's default startup with plain Uvicorn.
Do not change the production controller, its protected runner, Docker defaults,
Render tier, or start a separate migration-on-startup path.

Two distinct immutable release IDs/manifests/images and backup receipts:

1. Expand A, exact0168->0169. Amendment to UNAPPLIED0169 adds the same bounded
   slug->UUID / legacy eligibility helper definitions and owner/EXECUTE controls
   already accepted in0172. One trusted migration-only shared installer keeps
   these definitions consistent;0172 re-applies it idempotently.0169 does NOT
   force tenant RLS, drop service_access, tighten invitations or enable workbench.
   Existing application remains compatible if release A fails. Preserve helpers
   on schema downgrade; bounded reads are an additive compatibility seam.
2. Deploy and independently read back A API and every worker. Both API and frontend
   workbench flags are explicitly OFF, not assumed defaults. Schema169 does not
   have executed_at until171: workbench routes must return disabled before any
   workbench query, retention execution is forbidden. Ordinary auth/registration/
   invitations and worker startup remain compatible. Label EXPANDED_NOT_FINAL;
   this is not head/schema isolation/feature GO.
3. Contract B, exact0169->0172, only after A compatibility acceptance. Applies0170
   invitation isolation,0171 retention,0172 tenant isolation in Alembic order.
   Previous image must be compatible A. Rollback is APPLICATION rollback to A,
   NOT Alembic downgrade, wide RLS restoration or old168 binary. Final revision
   must equal the single repository head172 with exact controls/readback.
4. Enable bounded workbench only after final-head and accepted user-flow gates,
   through an exact environment/release packet. No cleanup scheduler activation
   or notification/mail/AI/STT dispatch as an incidental release step.

## DEV adaptation and validation

Canonical DEV schema gate gains an explicit bounded workbench expand phase,
allowed ONLY for repository head0172 and exact current0168->target0169 (or already
0169), with readback EXPANDED_NOT_FINAL. Default head verification remains
unchanged. An explicit contract phase permits current0169->head0172 only after
root's frozen compatibility acceptance packet. Neither intermediate phase can
be reported as default PASS/head-equivalent. Reject unknown phases/revisions,
backward/skip paths BEFORE mutation. Existing canonical project/env checks stay.

Gate subprocess output is captured, never raw driver/URL diagnostics. Failure
reports use safe class/reason codes only. Fresh readback required after mutation.
Both phases use existing free DEV project; provider deploy remains no-migration
with a separately accepted schema-phase evidence binding, not ignored schema drift.

Permanent QA verification may assert an explicit exact0168 (before),0169 (A),
or0172 (B) revision from the matching frozen packet. Default remains0168 and no
arbitrary revision/set is accepted. Bootstrap stays restricted to its original
0168 contract; this amendment authorizes verification only, not stand recreation,
reset or new business fixtures. Record the asserted revision in safe evidence.

Owned neighbor validation reconstructs baseline source controls BEFORE amended169
adds a tenant owner policy, then proves169 expansion without restrictions,
171 retention and170/172 isolation deltas. Do not compare169's deliberate extra
policy with legacy26 or silently remove it to claim baseline equality. Keep the
full baseline ACL/FK/trigger/function proof, negative scenarios, exact cleanup
and public neutrality. Tenant helper gate also proves expand then restrict.

## Ready, done and stop conditions

Ready: root verified exact-mode controller and existing plain-Uvicorn Compose;
cheap read-only compatibility inventory accepted with no GO claim. Local tests
prove shared helper invariants,169 additive/no restrictive SQL, repeat0172,
disabled workbench before DB, bounded DEV phase routing/readback/sanitization.
Owned DEV populated/empty migration and existing tenant/invitation/assignment
matrices PASS. Frozen Test Runner acceptance precedes any public change.

Done: DEV A compatibility plus DEV B final-head/browser acceptance; protected
production A and B identities/backup receipts/runtime workers/DB controls and
synthetic user journeys read back, feature visibility proved under exact flags.
Release Runner enforces existing hard gates, stops first failure. Root owns
shared installer/migrations/schema gate/integration; delegated writers may own
named paths only. Evidence and failed runs remain immutable and sanitized.

Stop if public revision drift, helper owner/ACL mismatch, flags not OFF in A,
missing compatible rollback, unexplained startup/worker query to171 objects,
unknown provider cost, failed backup/cleanup, or any isolation failure. Do not
upgrade a tier, weaken tenant policies, bypass gates or change customer records.
