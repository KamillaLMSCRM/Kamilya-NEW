# Controlled workbench activation release addendum V1

Status: Accepted by root2026-10-02 BEFORE implementation under owner's request to
continue the agreed DEV then production plan. Approved by: root technical owner;
human product owner retains scope, irreversible action and billing authority.
Supersedes: STAGED_COMPATIBILITY_RELEASE_ADDENDUM_V1.md only for final B activation
and native artifact configuration. Predecessor/A27 evidence remain unchanged.
Reason: successful A26/API and A27/frontend compatibility/OFF is accepted; an
enabled build must be explicitly bound to its release packet, not accepted merely
because a build-config claims true. Complements NAVIGATION_ACTIVATION_ADDENDUM_V1.
Change control: new version/addendum for another interface or invariant; no edits
to accepted predecessors. Root owns integration/release, independent reviewer and
Test Runner verify; leaf writers own only named fixtures/tests.

## Objective, states and excluded impact

Active methodologist can enter the private workspace and execute the existing
bounded text assignment through preview and explicit confirmation, with verified
receipt/replay and isolation. No voice/LLM/STT, course generation/edit/publication,
retention scheduler, mail dispatch, tenant recreation, paid resources or wider roles.
State progression: A/schema169/OFF -> DEV schema172/OFF verified -> exact B API,
worker/frontend enabled in DEV -> accepted synthetic live journey -> production
schema172/compatible B binaries -> controlled flags -> independent live acceptance.
Never activate on169. Application rollback is compatible A26 with flags OFF; no
schema downgrade or relaxed RLS. Existing manual assignments remain available.

## Native build and release interface (root-owned)

- Host's privileged manifest remains exact8; no helper installation or privilege
  change. Build-config remains exact6/schema1/source/version/archive/manifest
  digests plus typed boolean workbench_enabled.
- Build workflow adds one boolean dispatch input workbench_enabled defaultfalse;
  validates literal environment true/false BEFORE build. The same actual value
  enters Next.js build and digest-bound attestation. True is forbidden before
  product0.11.28; immutable27 stays OFF-only. Fresh exact-run artifact download,
  runtime archive/sidecar/path/capacity/rollback checks remain mandatory.
- Release packet schema1 remains byte-shape-compatible and means OFF. Schema2
  requires the one extra workbench_enabled field of exact bool type, no unknown
  fields. V1+enabled artifact, malformed config, missing attestation, legacy unknown
  flag with V2, or packet/artifact mismatch fails BEFORE host/staging mutation.
- Inspector accepts typed true only for >=0.11.28;27 literalfalse checks persist.
  Preflight and post-preflight reinspection both enforce packet/config equality.
  Technical evidence carries the observed typed flag; bridge binds its handoff to
  the frozen packet's requested flag. Legacy V1 reports may omit flag only as OFF.
- Source is trusted only through exact CI/artifact provenance, never cached local
  contents. An enabled frontend packet cannot alone authorize API/DB activation.

## Runtime/provider gates (root-owned, existing targets only)

DEV uses the approved existing Supabase public gate and immutable accepted A26
compatibility receipt for exact169->172, then independent public/QA/isolation
readback. Provider release targets only existing free Render API/worker and Hobby
Vercel DEV project; freeze exact source and literal runtime/build flags. The
existing controller must expose exact validated inputs and report observed flags;
missing support is repaired at that seam under this addendum, not ad-hoc provider
mutation. Production uses existing protected release/migration and reviewed
SSH helpers, fresh signed169 backup, exact172 readback and compatible rollback.
Freeze all four API/worker image identities and flags; timers return active with
observed current expected keys. No ingress/DNS/Proxmox/billing changes.

## Data ownership, errors and verification

Stateless release/configuration metadata only; assignment state, tenant context,
plan TTL15min/unexecuted cleanup+24h/receipts90days remain existing owner contracts.
Release lock and idempotency remain existing controller behavior. Disabled routes
must reject before workbench query on A. Malformed/unknown/mismatched identities,
schema/flags, failed backup, missing rollback or provider cost stop before mutation.
Root records failed gate and safe state; never silently retries partially applied
operations or turns technical health into product GO.

Before source changes, test producer-consumer contract RED for explicit true28,
legacy27 rejection, strict packet schemas/types, false/default preservation, flag
mismatch before stage and drift between preflight/execute. Run native controller,
bridge and unchanged host-helper regressions, scoped quality/version/graph checks.
Before release run full risk-based CI and exact enabled build. DEV/prod verify real
worker identity/queues, final172 FORCE RLS/ACL/non-bypass, two synthetic tenant
negative cases, methodologist preview/confirm/replay, loading/error/reload/mobile,
unchanged manual/student/admin roles and no unintended outbox dispatch.
Done requires exact runtime/schema/flag and live business receipt/cleanup proof;
local tests, HTTP200 or agent READY are not GO. Existing synthetic fixtures are
reused; disposable fixtures require exact ownership/cleanup and no real PII.
