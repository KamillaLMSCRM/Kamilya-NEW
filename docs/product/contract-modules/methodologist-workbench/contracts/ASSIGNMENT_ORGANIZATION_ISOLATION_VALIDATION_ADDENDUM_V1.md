# Assignment organization / neighbor isolation validation addendum V1

Status: Accepted by root for bounded local and synthetic DEV validation,
2026-10-01, under owner's "продолжай". Extends prior assignment addenda without
rewriting them. Product owner: user; root owns integration/gate/DEV; cheap leaf
review is read-only; Test & Evidence Runner owns independent local acceptance.

## Objective / interface / negative space

Prove tenant/actor denial and rejection of organization edits that commit before
the guarded audience selection. Preserve explicit user placement over position
fallback, opt-in descendants and one-time semantics. A new hire after guarded
selection is not automatically assigned. Do not claim serializable org mutation,
global predicate locks, trigger/FK equivalence or future automatic assignment.

Writes permitted only in owned validation scripts/tests and contract/index/
canonical plan/backlog/handoff/changelog/error records. Application/auth/org/
enrollment code, migrations, roles/grants/policies in public, providers, workers,
flags, tenant data and retention policies may not change under this addendum.
Unexpected business defect requires root impact amendment before affected edits.

## Metadata preflight

Add a read-only metadata mode to the canonical owned gate: canonical Supabase DEV
identity/owner/runtime validation, READ ONLY transaction, exact named neighbor
tables. Read pg_class/pg_policies/pg_roles and effective lms_app privileges only;
never select user/invitation rows, token/email/payloads or arbitrary function data.
Output only table/policy names, flags, privilege names and bounded classification,
not raw policy expressions/DDL. Record absent/drift/legacy exceptions honestly.

Existing source0046 public pending-invitation SELECT and tenant RLS ambiguity are
not to be copied as "safe" or silently replaced with a stricter fixture and then
claimed equivalent. No arbitrary live DDL execution. Source/live mismatch blocks
equivalence only; independent organization/owned-plan gates can continue.

## Synthetic verification

Use the same validated random workbench schema, owned-only search_path, accepted
enqueue body, synthetic roles/identities and exact cleanup. No public data reads
or writes beyond bounded metadata. No customer/permanent QA-stand mutation.

Exercise foreign actor/tenant owned-plan GET+confirm, direct explicit placement
versus active position fallback, descendants opt-in, committed employee placement
move, committed position relocation and committed child reparent. Guarded confirms
must reject changed exact audience, leave plan ready and create no domain effects.
Where concurrency is claimed, use distinct runtime sessions and observe a blocked
lock before releasing the committing edit; no sleep-based guess of interleaving.

Keep metadata-only state outside functional PASS. Focused guards/neighbor tests,
actual PostgreSQL interleavings, independent review and frozen-candidate local
Runner acceptance required. Drop only generated schema; absence/public revision+
table inventory neutrality mandatory. Metadata-only mode creates no fixtures.

## Rollout / stop / completion

Both flags remain off; no public migration/release/mail/OTP/AI/audio/billing action.
Stop on unexpected public resolution, identity/role mismatch, unsafe metadata
emission, leaked token, unexpected write or insufficient contract. Root records
disposition and impact amendment before new business changes. No privilege bypass
or fabricated equivalence. This slice is complete only for named proved gates;
unresolved neighbor policy/FK/trigger, browser and retention gates stay explicit.
