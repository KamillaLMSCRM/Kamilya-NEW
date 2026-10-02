# DEV activation controller addendum V1

Status: Accepted by root2026-10-02 BEFORE implementation under the owner's
approved DEV-then-production workbench plan. Root owns provider integration;
independent reviewers and Test Runner verify. Complements CONTROLLED_ACTIVATION
RELEASE V1; no change to assignment, tenant, retention or billing contracts.

## Public seam and ownership

Extend existing scripts/deploy/dev_release_controller.py, not a second provider
script. Legacy kamilya-dev-release-v1 execute/reconcile remain unchanged and never
configure flags. New kamilya-dev-release-v2 has the same exact top-level fields
plus workbench_enabled (exact boolean), configuration_ci_run_id (positive exact
integer) and schema_evidence (exact path/sha256 strings). Reject unknown fields,
duplicate JSON keys, nonboolean flags and paid/unknown plans; V2 permits only the
existing Render Free / Vercel Hobby DEV targets. Migration scope stays none:
the controller cannot migrate a database or substitute provider readiness for RLS.

New prepare command requires exact release-ID confirmation. Before configuration:
validate the immutable local schema-gate receipt digest, canonical target and
current/expected0172 PASS; verify exact source CI run SUCCESS on master/push and
the remote master source SHA; verify DEV still equals expected_previous_sha;
verify all provider identities/branches/plans; inventory all three existing flags.
Require one unambiguous literal true/false value per flag, and frontend flag only
in the DEV project's production target, not a shared preview/development row.

Prepare changes only METHODOLOGIST_WORKBENCH_ENABLED on the two named Render
services and NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED in the named Vercel DEV
project's production target. Preserve every other environment key, secret, target
and provider setting. Idempotently skip matching values. Read all three back
after mutation and return CONFIGURATION_READY, provider flags and changed labels;
runtime activation is explicitly NOT_VERIFIED_UNTIL_EXACT_DEPLOY_AND_LIVE_TEST.
Do not move Git branches, create resources, redeploy, or claim product GO here.
If an update/readback fails after one mutation, stop with the sanitized gate;
do not silently roll back or continue the remaining provider changes.

V2 execute/reconcile revalidate the bound schema receipt and all observed provider
flags before push/deploy, and again after terminal exact-SHA deployments/health.
They never repair flag drift. Evidence names observed provider configuration and
requested flag, distinct from runtime/browser acceptance. Existing deploy reuse
is safe only for the uniquely versioned new source; prepare must precede the DEV
branch push. Root performs the canonical project push and independent readback.
Application/build flags must be independently verified live before DEV GO.

## Evidence, errors and verification

Schema receipt is local immutable release metadata within the checkout's canonical
.release-evidence, at most4096 bytes, regular nonsymlink, digest checked before
JSON parsing or any provider call. No secret or environment values except these
three public/nonsecret boolean flags enter evidence. Existing sanitized error
codes, bounded4096-byte reports and no blind provider-mutation retries remain.

RED-before-code tests cover typed packet/unknown fields, schema digest/revision,
confirmation/branch/source-CI/free-plan failures before setters, idempotent prepare,
only exact flag setters, readback mismatch/partial-stop, legacy no setters,
V2 execute/reconcile drift denial and observations without product GO. Adapter
tests assert exact single-key payloads and production-only Vercel target. Root
and independent runner then verify real existing-target identities, schema/RLS,
worker queues and browser preview/confirm/replay. No new resources or cost.
