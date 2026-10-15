# Manual Codex CLI reserve V3 — dormant DEV/production installation

Status: owner-requested installation boundary,2026-10-15; not activation or vendor entitlement.
Extends V2. Owner instruction: complete DEV, install connector/control in production,
leave reserve OFF for explicit later owner activation. Root owns integration/release.

## Scope and invariants

Ship one exact immutable application release with additive0179->0180 and a separately
digest-bound official CLI connector image on existing approved infrastructure.
No provider tier, paid capacity, API billing, voice, public connector ingress, DNS,
Proxmox, privilege expansion or unrelated tenant change. Reserve OFF is a stored
route invariant before/after every migration, deployment, readiness and smoke.
Do not temporarily enable the persisted production route to test fallbacks.

Current owner authority covers dormant installation and isolated synthetic technical
acceptance, not a claim that a personal subscription is approved for commercial
hosted inference. Keep that applicability question explicit before customer-serving
activation. Local CLI success and manual enable capability do not establish vendor
entitlement, quota, data-handling suitability or service-level guarantees.

## Verification and deployment order

1. Run source-bound0156+0180 migration in a uniquely owned canonical Supabase DEV
   schema; prove populated upgrade/downgrade/re-upgrade, exact default route OFF,
   FORCE-RLS and unchanged policies, non-bypass runtime reads and denied ordinary
   context writes, constraint negatives and refused populated downgrade while ON.
   Delete only that schema; prove public schema and public route neutrality.
2. Apply0180 through the canonical public DEV schema gate. Deploy exact application
   SHA on existing DEV tiers. Unchanged flags can use the existing no-mutation
   deployment controller after the separately owned schema gate; this is not a
   claim that the controller itself migrated or accepted schema0180.
3. Use only a verified private transport for the real DEV connector acceptance.
   Public Render currently has no proved private route. Do not create a public
   connector port or a paid relay to disguise that gap. A temporary private DEV
   acceptance runtime on existing capacity must use canonical DEV DB/auth/synthetic
   fixtures, isolated secrets and deterministic cleanup; report its exact contour
   separately from public Render readiness. Stop if such isolation cannot be proved.
4. Bind successful CI, image provenance, backups, exact current production/schema,
   compatibility and capacity, then normal protected backend/native frontend gates.
   Product version0.11.53 binds current migration179->180; versions51/52 retain
   their179 schema contract. Controller changes may only extend that version map,
   with independently verified installed bytes, backup and existing protected
   upgrade workflow. No rights/configuration broadening.
5. Install only the connector's dedicated compose project/private network/auth
   directory and application bearer configuration on the approved application
   runner. Validate mounts/resources/network and rollback before start. Managed
   CLI login remains official, protected and refreshable; no raw browser token form
   or token in arguments/logs/Git. Owner workstation auth is not a release artifact.
6. Independently read API/worker/frontend identities, schema180, all flags unchanged,
   exact stored order/revision unchanged and reserve OFF. Exercise superadmin
   control/readiness, ordinary-role denial, synthetic direct connector response and
   cancellation without enabling the saved route. Preserve real tenant data.

## Stop and rollback

Stop on unknown identity, failed gate, access/transport ambiguity, insufficient
existing capacity, secret exposure, unexpected data/route change or required new
paid/public/privilege scope. Do not bypass a failed controller. Roll back only the
exact approved services/configuration, preserving original route and protected
current/rollback artifacts. Schema180 is additive; downgrade requires OFF and the
normal migration backup/restore gate, never silent route mutation.

Completion means actual DEV and production identities plus installed connector,
visible superadmin control, technical response/readiness and persisted OFF readback.
Source/test/CI alone is not installation; dormant installation is not activation.
