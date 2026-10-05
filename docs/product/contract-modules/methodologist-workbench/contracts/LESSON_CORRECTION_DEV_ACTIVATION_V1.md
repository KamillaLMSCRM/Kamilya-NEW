# Lesson correction DEV activation V1

Status: Accepted for LOCAL implementation before product writes, 2026-10-06.
Approved by: root integration owner under the owner's DEV-then-production plan
and current continuation. Product owner: workspace owner. Module/root owner: root;
reviewer: independent bounded reviewer and persistent Test & Evidence Runner.
Extends DEV_ACTIVATION_CONTROLLER_ADDENDUM_V1; preserves accepted V1-V4 packets,
correction/UI/lifecycle contracts. New authority, billing or invariant changes
require owner approval; technical delta requires a versioned impact addendum.

## Objective and interface

An exact existing-free DEV deployment can enable draft lesson correction without
manual provider operations or weakening schema/CI/source identity guards.
Existing dev_release_controller.py owns prepare/execute/reconcile; new strict
kamilya-dev-release-v5 is V4 plus lesson_correction_enabled (exact boolean),
with exact canonical public-schema0178 receipt. Both document_draft_enabled and
lesson_correction_enabled require workbench_enabled when true, independently;
correction does not require document drafting. Migration_scope remains none:
the separate canonical schema gate owns additive0176-0178, never the controller.

## Integration and data ownership

Map: immutable V5 packet -> schema/source-CI/previous-source/free-provider guards
-> inventory workbench+document+correction flags -> confirmed prepare -> exact
DEV deployment -> provider/runtime/browser acceptance. Provider adapter owns
single-key configuration requests; application owns all correction data.
V5 adds correction_flags/set_correction_flags adapter operations. Read bounded
complete inventories; absent correction flags mean default false, duplicate,
nonliteral, malformed/incomplete or shared-target rows refuse. Frontend flag is
plain and exclusively [production] in the existing named DEV Vercel project.
All nine flags must have valid inventory before the first setter. Matching flags
are idempotently skipped; every changed key is immediately read back. First
failure stops remaining writes, with no blind retry or autonomous rollback.

Prepare changes only METHODOLOGIST_LESSON_CORRECTION_ENABLED on the two named
Render Free services and NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED in
the named Vercel Hobby DEV production target, plus already accepted packet-bound
workbench/document keys if drifted. No other keys/settings/resources change.
Execute/reconcile refuse any requested/observed drift before push/deploy and
recheck configuration afterward; configuration is not runtime/product GO.

## Read/write scope and negative space

Write: existing DEV controller, new V5 tests, exact existing CI selector, canonical
plan/module index/changelog/errors and Runner append-only ledger. No application,
migration, frontend business logic, queues, schedules, roles, secrets, limits,
production/native controller, landing, DNS or paid-resource changes. Existing
V1-V4 must never invoke correction methods or gain new mandatory fields. Reuse
existing bounded document inventory transport; do not create a second controller.

## Verification and rollout

Pre-agreed seams from the approved deployment plan: packet validation and public
prepare/execute/reconcile with synthetic provider boundary; live HTTP adapter
inventory/single-key payload/readback. Tracer RED before minimal V5 admission,
then guards, shape/free/CI/schema/idempotency/partial-failure/legacy regressions.
Root and independent Runner review exact frozen sources; run full controller
neighbors and scoped quality/CI selector contracts. Only after source gates pass
prepare an immutable existing-target DEV packet and independent release preflight.
Actual schema/prepare/deploy require separately verified current target and owner
scope; this document does not execute or authorize external writes by itself.
Rollback keeps additive schema and disables correction via a separate reviewed
exact packet, or deploys verified compatible previous code. No schema downgrade
with populated accounting. Live browser, real-provider semantics and learner
history remain required before product/public-production acceptance.

Stop: unknown/paid provider tier, ambiguous target/previous/rollback, hash/CI/schema
drift, inventory refusal, external unknown outcome, unlisted module, destructive
or cost scope expansion. Preserve failure receipts and reconcile before retry.
Ready: exact V5 contract/test seam and scope frozen. Done: local independent
acceptance plus separately owned exact DEV/runtime/browser/cleanup evidence;
local implementation alone is not DEV or production completion.
