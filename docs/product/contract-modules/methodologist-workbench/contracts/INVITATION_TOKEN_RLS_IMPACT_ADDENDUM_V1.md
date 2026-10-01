# Invitation exact-token RLS impact addendum V1

Status: Accepted by root, 2026-10-01, under owner's explicit "делай" on the
invitation-isolation remediation. Extends organization validation V1; does not
authorize public DEV/production migration, deployment, provider or billing work.
Product owner: user. Root: module/contract/migration/integration/DEV owner.
Independent cheap investigator/reviewer: read only. Test Runner: local acceptance.

## Trigger / disposition / responsibility

DEV catalog and source0046 confirm a permissive pending SELECT for PUBLIC without
tenant or exact-token restriction. No business rows or API exploit were inspected.
The previous validation-only write scope excludes this fix: root stops that scope
and accepts this explicit interface/invariant impact before affected edits.
User-visible objective: tenant operations cannot read foreign invitations;
anonymous possession of an exact link still resolves only that invitation and
continues through existing tenant context, masked view and scoped OTP policy.

## Interface / invariants / errors

One private lookup helper is shared by public view and pending activation lookup.
It binds app.invitation_token transaction-locally using a parameter, selects by
exact token equality, then clears token context before returning. On a DB failure
caller must rollback (existing get_db dependency already does); no swallowed error,
no commit/activation/mail in lookup. No normalization/truncation or token logging.
No new endpoint, DTO, role, auth/session lifetime, OTP or delivery change.

Replace only legacy public pending policy with SELECT TO lms_app requiring EMPTY
tenant context AND the exact nonempty token. Ordinary tenant policy remains. No
status predicate in the token capability: existing public DTO/source intentionally
distinguishes accepted/expired/revoked/superseded links. Activation still rejects
non-pending states/expired times and requires existing purpose-bound OTP. Exact
token possession is public credential, not permission to enumerate any other row.
Token context cannot grant INSERT/UPDATE/DELETE or override an authenticated tenant.

State/data ownership unchanged: invitations owned by users; lookup scope is local
transaction state only, cleared on success/404 and rollback after SQL failure.
No retention/delete scheduler introduced. No global/predicate concurrency claim.

## Impact / permitted read and write scope

| Existing module | Impact | Compatibility gate |
|---|---|---|
| users invitations | private interface + RLS invariant | both public callers, exact token, masked payload, terminal reasons, OTP |
| auth/tenant context | consume existing set_current_tenant only | role/session/OTP unchanged; no foreign token in authenticated context |
| DB migrations | additive0170 root-owned | owned current definitions, forced RLS, negative2-tenant proof; public untouched |
| workbench/enrollments | none | focused existing preparation/execution regressions |

Writes: new0170 migration; invitations_service.py private lookup and two callers;
owned invitation token-RLS/unit/public-view tests; new isolated invitation gate;
contract/index and canonical plan/handoff/backlog/changelog/error/ledger records.
No kiosk/login helpers, workers, public roles/grants, other policies/tables,
frontend, tenant/customer/QA records, provider or production changes permitted.
Use0119 kiosk exact-token policy as source precedent, not SECURITY DEFINER bypass.

## Verification / configuration / observability

Canonical local wrapper, scoped Ruff/Python baseline; synthetic Supabase DEV only,
fresh invitation_<12hex> schema, fixed owned,pg_catalog search_path, runtime lms_app
non-superuser/non-bypass. Clone definitions only; install SOURCE0042 tenant policy
and FORCE RLS for the invitation table plus accepted0170. No arbitrary live DDL.
Before fixing, demonstrate0046 broad visibility using synthetic IDs only. After:
no context/wrong token/empty token invisible, tenantA hides tenantB pending even
when a foreign token setting exists, anonymous exact token returns exactly one
row for every status, normal own-tenant reads/mutations preserved, anonymous write
denied, transaction-local scope cleared on commit/rollback, shared actual helper
and activation rejection exercised without sending/accepting OTP or email.
No tokens/payloads/real rows in evidence; static IDs/counts/check names only.
Cleanup exact generated schema, independent absence, public revision/table inventory
neutrality required. Full unrelated neighbor RLS/FK/trigger equivalence not claimed.

## Rollout / rollback / stop / readiness and done

Local only now. Future release must stage compatible API helper BEFORE migration:
new helper works under0046; old API is incompatible with narrowed anonymous policy.
Do not downgrade to0046's broad policy as recovery.0170 downgrade fails closed with
explicit roll-forward requirement; preserve patched lookup in any API rollback.
An eventual release packet must prove this exact ordering/old-API exclusion.
No public apply/flags/mail/AI/audio/spend inferred from acceptance.

Ready: trigger/source/callers/precedent/tests read, root impact accepted.
Done: original synthetic trigger reproduced; patched exact-token/tenant negatives
and legitimate states PASS; focused neighbors/quality, independent patch review
and exact local Test Runner acceptance; cleanup/readback and sanitized evidence.
Stop on foreign/public table resolution, identity mismatch, unlisted module,
unsafe output, loss of public compatibility, unavailable required DB proof or scope
expansion; root records disposition before resuming. Production remains NOT FIXED.
