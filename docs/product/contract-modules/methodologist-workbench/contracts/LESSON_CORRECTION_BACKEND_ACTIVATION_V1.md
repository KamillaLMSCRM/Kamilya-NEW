# Lesson correction protected backend activation V1

Status: Accepted for LOCAL implementation by root integration owner, 2026-10-06,
under the owner's approved correction DEV-then-production objective. This is the
separate backend impact addendum required by NATIVE_ACTIVATION_V1, not a release
or maintenance verdict. Owner approves business, billing, access or resource
expansion; root owns integration and exact external gates. Accepted V1 is
immutable; incompatible changes require a successor.

## Responsibility and interface

The existing protected two-slot release plane binds one immutable API image and
three non-secret feature booleans to API and all three workers. It does not decide
lesson authorization, source provenance, AI admission, tenant policy or publication.
Application owners retain those responsibilities. No raw environment is logged.

Release manifest schema2 extends schema1 with product_version, feature_flags and
previous_feature_flags. Both flag objects have exactly workbench, document_draft,
lesson_correction, all literal JSON booleans. Document/correction ON require
workbench ON; document and correction are otherwise independent. Correction ON
requires version >=0.11.39 and schema0178. Exact correction upgrade is0175->0178
with explicit rollback compatibility; no-migration correction requires readback
at0178 before starting the candidate. Schema1 remains shape/behavior compatible
and never invents explicit flag verification. Duplicate JSON keys fail closed.

The workflow supplies reviewed JSON flag objects rather than more individual
dispatch fields. Blank flag objects retain schema1; both present produce schema2.
Unknown, absent, duplicate, string-valued or inconsistent flags fail validation
before host execution. Exact SHA/version/tag/CI/image/backup gates remain.

## Ownership, ordering and rollback

Fixed compose anchor maps only the three feature keys; explicit per-slot process
overrides take precedence over the existing runtime.env without editing it.
Schema1 reads the existing runtime-file defaults. No secrets, access, ports,
resources, queues, schedules, mounts or host configuration change.

Before pull/migration, schema2 verifies the current four-container image/running/
restart identity and exact previous flags. Candidate API flags are checked before
old workers stop; all four candidate containers are checked before proxy switch.
Already-deployed replay re-verifies all four current flags and exact health/version
rather than treating a state file as runtime proof. Receipts include only typed
requested/previous flag objects. Flag mismatch is a hard failure, not a retry.

Failure uses previous_feature_flags with the previous image/SHA, verifies all four
restored containers and health, and retains the additive schema. Existing backup,
migration receipt, lock, append-only evidence and proxy rollback mechanisms stay.
Future explicit rollback packet swaps candidate/previous flags. New correction OFF
does not silently turn off existing workbench/document features.

## Source-derived impact and write scope

release-kz-production workflow -> strict ReleaseManifest -> ReleasePlane slot env
-> shared compose anchor -> four containers -> selected-key Docker readback ->
existing evidence/proxy/state. Bundle upgrade already owns controller and compose;
upgrade-kz-release-plane uses exact CI/controller hash and protected installation.
Static graph edges cannot prove these workflow/host/runtime relationships.

Root owns scripts/deploy/release_plane.py, infra/compose/kamilya-release-slot.yml,
.github/workflows/release-kz-production.yml, new focused activation tests and
existing neighboring release/bundle/workflow tests/CI wiring/docs. Existing fixed
wrapper, upgrader privileges/configuration and target paths remain unchanged.
Forbidden: arbitrary SSH/config edits, new sudo/access, migrations/application
policy edits, customer/QA history changes, providers/tiers/billing/resources,
DNS/landing, queue/concurrency/retention changes and broad cleanup.

## Verification and external gates

Database/network-free RED/GREEN: schema1 compatibility, strict schema2 shape/types/
dependencies/version, duplicate rejection, every service flag drift, zero pull or
migration on previous drift, candidate refusal before old-worker stop, exact backup
order and receipt replay, no-migration0178 gate, already-deployed drift refusal,
rollback restores previous flags and preserves runtime.env, sanitized failure
receipts. Neighbor release/workflow/bundle/native tests and scoped quality remain.

Production requires independent current controller/image/SHA/schema/flags readback,
exact CI/version39 release/tag, immutable bundle/controller readback after the
existing protected upgrade, backup/restore175 plus compatible0178 restore proof,
exact protected release/native packaging and bounded live correction acceptance.
Stop at any failed/ambiguous gate. A local PASS is not production GO. No additional
cost, resource or maintenance authority is inferred from this contract.
