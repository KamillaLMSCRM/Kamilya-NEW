# Lesson correction native activation V1

Status: Accepted for LOCAL implementation, 2026-10-06. Not a release verdict.
Approved by: root integration owner under the owner's correction DEV-then-
production objective. Product owner: workspace owner; module/root owner: root;
reviewer: bounded independent reviewer and persistent release/test workers.
Root froze this contract in the leaf implementation packet before delegated
writes; this file records that packet. DEV_ACTIVATION_V1 remains DEV-only.
Change control: root accepts compatible technical addenda; owner approves new
business, authority, billing, destructive or resource scope. Accepted V1 stays
immutable; changes require a versioned successor.

## Responsibility, interface and contribution

Native release orchestration admits one exact frontend artifact whose explicit
correction visibility matches its approved packet. It never decides whether a
lesson may be corrected; existing application authorization/provenance/apply
owners retain that policy. It does not enable backend flags, migrate a schema,
execute AI, change server access or update the privileged deploy helper.

Inputs: existing ReleasePacket plus strict schema4 lesson_correction_enabled
boolean, exact SHA/CI/native build/current/rollback identities and owner scope.
Outputs: existing technical preflight/deploy/failure records with typed correction
configuration binding. Schema1-3 remain compatible, correction OFF and omit the
new packet field. Correction true independently requires workbench true; document
drafting may be false. Existing document dependency remains unchanged.

Native build input supplies a literal true/false public correction key. At product
version >=0.11.39, build-config schema3 includes all three feature flags, exact
source/version/archive hash and privileged-manifest hash. Version38 retains
schema2; earlier compatible versions retain schema1. Correction ON below39 is
refused. The root-owned privileged manifest keeps its exact eight fields.

## Ownership, state, invariants and errors

Root owns the release packet/decision; CI owns immutable artifact metadata;
controller owns ordered technical evidence; the existing host helper owns
staging/switch/rollback. No application/tenant state ownership moves.
State: requested -> locally validated -> bound artifact -> host preflight ->
existing deployment/readback or BLOCKED. Product acceptance is separate.
Malformed/nonliteral/missing/duplicate/unknown metadata, version incompatibility,
packet/artifact mismatch or identity drift fails before any host operation.
Bridge schema4 requires explicit typed matching correction readback; older
schemas default OFF without inventing evidence. Success and failure receipts
propagate the requested/observed flags without claiming runtime semantics.

Idempotency/concurrency, capacity/rollback guards, immutable source/archive,
transport paths and stop-first-failure behavior are inherited unchanged. No
automatic retry, rebuild, fallback credentials or blind partial-deploy retry.
Configuration is non-secret; raw environments, credentials and tenant payloads
never enter artifacts or logs. No new endpoint, database, schedule or resource.

## Impact map and permitted scope

SOURCE-DERIVED map: native workflow -> eight-field manifest + schema3 build config
-> ct137_native_release artifact/packet seam -> release_runner_bridge technical
binding -> unchanged privileged host helper. Graph edges cannot establish CI or
host transport; confirm these cross-language relationships in source/contracts.

Interface impact: build-native-frontend.yml, ct137_native_release.py and
release_runner_bridge.py. Tests: new test_correction_native_activation.py,
existing document/native/workbench/bridge neighbors and CI selector contract.
Root owns CI wiring, this contract, module index and release documentation.
Write scope is only those sources/tests/docs. Read scope includes these owners,
their fixtures, version/config conventions and existing frontend runbook.

Forbidden: privileged helper, backend release plane/configuration, migrations,
application correction policy, roles/tenancy, retained history, providers/plans,
DNS/proxy topology, queues/timers, landing, secrets, limits and retention.
Backend activation and actual production migration require a separate accepted
impact addendum and exact external release gates; this contract grants neither.

## Verification, rollout and stop conditions

Database-free RED/GREEN at the packet/artifact/bridge interfaces; strict shape,
duplicate/hash/version/dependency refusal; zero host calls on mismatch; schema1-3
serialization/behavior unchanged; executable Node workflow guards; scoped quality
and all native/document/workbench/bridge neighbors. Root verifies combined source
and CI entrypoint, synchronizes graph once after changes, independently reviews
exact artifact/config hashes before an exact protected production release.

Existing capacity, current/rollback and off-host recovery checks remain hard
gates. No deletion or host maintenance is inferred from this local contract.
Runtime rollback uses the existing exact previous native artifact; never rewrite
it or pretend an old build has correction enabled. Backend/schema compatibility
and live product acceptance must be independently proved before public GO.
Stop for unlisted module, weak/unknown configuration, mismatched packet/artifact,
ambiguous target/rollback, insufficient capacity, failed guard or new authority.
Root records the blocker and accepts a versioned addendum or cancels.
Ready: typed scope/ownership/interfaces frozen in root packet.
Done locally: independent focused/neighbor/quality/CI-seam acceptance. Released:
separately authorized exact artifact/deployment/readback and bounded user flow.
No latency/cost SLO changes; local instrumentation measures actual commands only.
