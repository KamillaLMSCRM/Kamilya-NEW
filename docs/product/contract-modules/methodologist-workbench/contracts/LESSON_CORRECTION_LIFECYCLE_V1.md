# Lesson correction lifecycle V1

Status: Accepted for LOCAL + owned synthetic DEV implementation, 2026-10-05.
Approved by: root integration owner after independent contract review and exact
P1/P2 dispositions below, under owner's approved plan/current continuation.
Root/module/migration owner: root; product owner: workspace owner under approved
correction plan, retention durations and current "продолжай". Reviewer: bounded
independent cheap reviewer, then frozen Test & Evidence Runner. Root may accept
technical impact within scope; owner approval required for durations, billing,
production, authority or data-scope expansion. Accepted predecessors stay immutable.

## Objective, interface and scope

An interrupted proposal must become an honest terminal result without a duplicate
provider call or a refund against the wrong month. Workbench metadata must have
bounded retention without deleting lessons, publications, assignments or learning
history. Existing public create/read/apply/receipt seams remain unchanged.

Workbench lifecycle owns an internal accounting record and one operational DB
interface `maintain_workbench_lesson_corrections(integer,boolean)`. Inputs: existing
transaction-local tenant and superadmin context, actual current_user=lms_app,
batch1..500 (default100), apply boolean (defaultfalse). No supplied time, tenant
enumeration, plan locator or arbitrary predicate. Outputs: plan UUID and action
only, no snapshots/prompts/source/proposal/PII. Caller owns commit/rollback.
No HTTP route, Celery task, scheduler, provider/resource/limit change or automatic
public cleanup. Public activation is separately gated.

Pre-agreed verification seams: public correction create/read/apply/receipt
operations and the bounded maintenance DB interface, under existing approved
module/retention plan. Unit tests cover public behavior; actual owned Supabase DEV
proves transactions, RLS, timestamps and SQL refunds, not fake-SQL shape alone.

## Accounting state and ownership

Additive0178 adds `workbench_lesson_correction_accounting`, one row per plan,
parent+tenant cascading FKs; tenant/actor, original UTC month, fixed10-cent estimate,
state, DB-created/provider_boundary_at/settled timestamps. provider_boundary_at
means only the durable pre-provider authorization marker, NOT evidence of provider
resolution, invocation or actual spend; started state has that same meaning.
No exact provider-cost claim.
RLS+FORCE RLS; existing non-BYPASS lms_app only. Ordinary owner reads/writes its
record; failure closure after role loss remains possible. Exact-tenant superadmin
maintenance reads/transitions/purges. No PUBLIC/anon/authenticated/service_role/
lms_recovery access, role/bypass/SECURITY DEFINER change.

New admission inserts reserved record atomically with unique claim and correction-
owned budget charge SQL. Original month comes only from immutable DB-derived
snapshot.created_at. Shared AI budget helper/defaults and all other callers remain
unchanged; correction does not call generic charge/refund helpers or process-clock
month guards. Correction charge preserves existing atomic INSERT/ON CONFLICT
positive-budget predicate and explicit integer casts, default5000 when settings
are absent/NULL, and correction-specific <=0 denial. No limit changes.
Crossing UTC month after the DB snapshot does not change its reserved month.
Before provider resolution, lock parent then accounting in a SECOND transaction,
commit reserved->started and DB timestamp; no provider resolution
or invocation may precede that successful commit. Commit uncertainty does not
justify a provider call. Success transitions started->charged atomically with ready.
Known failure follows existing optimistic-refund behavior. The accounting state
trigger, not an additional Python refund helper, updates exactly the stored
tenant/month/10 cents with sufficient aggregate cost/count predicates and RETURNING;
same transaction settles refunded and parent failed. Routine and maintenance
refunds use one executable DB owner path.
Missing/insufficient aggregate refuses closure and leaves accounting uncertain;
never clamp or refund another month. Terminal settlement is immutable/idempotent.

All accounting identity/month/estimate/time fields are DB guarded and immutable;
only state UPDATE is granted. Trigger owns timestamp transitions and verifies
parent identity and appropriate pending/ready/failed state. No business record
ownership moves. Parent-first lock ordering is shared by provider finalization,
recovery and deletion; budget row lock follows accounting. No long provider call
while DB locks are held. No automatic provider retry.

| Commit window | Durable state / recovery |
|---|---|
| T1 claim+charge+reserved insert fails before commit | All three roll back; no provider call |
| T1 acknowledgement lost | Caller does not proceed to T2/provider; replay sees either no record or reserved; maintenance refunds only durable reserved |
| T1 committed, crash before T2 | reserved/no-start is durable; expiry maintenance refunds original month |
| T2 start-marker transaction fails/rolls back | reserved remains; caller never calls provider; maintenance later refunds |
| T2 acknowledgement lost | No provider call by this caller; durable reserved or started is reconciled conservatively |
| T2 acknowledged, provider or T3 outcome unknown | started is durable; expiry maintenance retains estimate; no provider restart |
| T3 ready+charged or failed+refunded acknowledged/lost | Atomic terminal outcome; replay/read never recharges, regenerates or refunds twice |

T1/T2/T3 are separate commits. Acknowledgement failures are outside any catch
that assumes provider failure; no blind refund on unknown commit.

Existing plans have no trustworthy provider-start marker or per-plan accounting:
leave them without fabricated accounting rows. Legacy ready/apply behavior stays
compatible; legacy expired pending is closed failed conservatively with estimate
retained, never guessed/refunded. Old API remains compatible after additive upgrade
but cannot provide new accounting guarantees; rollout uses new API before enabling
correction. Downgrade refuses populated parent/accounting state; rollback keeps
additive schema and flags OFF, roll forward rather than erase evidence.

## Maintenance and retention

Dry-run is read-only/no record locks. Apply locks at most batch parents with
FOR UPDATE SKIP LOCKED, oldest eligibility timestamp then UUID. Frozen
transaction_timestamp is authoritative; no host clock, grace or TTL extension.
Pending becomes eligible at expires_at (15-minute preview lifetime, well beyond
existing bounded proposal timeout). Parent lock excludes live finalization:

- reserved/no-start accounting: fail with fixed proposal_interrupted and refund
  original month exactly once, settle refunded in the same transaction;
- started accounting: fail proposal_interrupted, settle retained; provider outcome
  is unknown, estimate is not refunded and generation is not restarted;
- no accounting (legacy): fail proposal_interrupted, keep aggregate untouched;
- terminal/malformed accounting paired with pending: refuse, not guess.

Late provider completion observes failed, never revives ready or refunds twice.
Ready/failed unexecuted parent is deletable at expires_at+24hours, not earlier.
Pending is never deleted directly. A parent with an application receipt is deleted
only at applied_at+90days, never by preview expiry; receipt/ledger cascade with
parent. Only workbench metadata is deleted. Missing/future/untrustworthy execution
time remains protected. Eligibility is inclusive; one microsecond younger is safe.
No same-call reconciliation then deletion: each selected parent performs one action.
After metadata removal GET/apply by old plan ID returns not found and cannot
reconstruct/reapply. Request-key idempotency is bounded by metadata retention;
explicit new create after removal can make a new plan, never restore/auto-apply old.

Exact-tenant superadmin failure UPDATE policy is additive, with WITH CHECK failed;
ordinary RBAC/owner policy unchanged. Exact-tenant superadmin SELECT on application
receipts is necessary for correct90-day classification under RLS; ordinary actor
receipt read/confirmation remains owned and unchanged. Ledger purge adds explicit
`DELETE FROM workbench_lesson_correction_accounting WHERE tenant_id = :tenant_id`
BEFORE application and parent statements in the existing exact-tenant purge.
Test order and tenant scoping explicitly; cascade is not a substitute for that
contract. No new broad delete path.

## Impact, invariants and write scope

| Owner | Impact | Protection |
|---|---|---|
| Workbench preview | Internal persistence extension | same public DTO/seals, one charge/call, role-loss closure, no duplicate refund |
| Workbench accounting/model0178 | New owned persistence | immutable state/time, FORCE RLS, exact tenant/month and batch bounds |
| Workbench application receipts | Additive maintenance SELECT |90-day historical GET protection, ordinary ownership unchanged |
| Existing AI aggregate | Existing owner-consumer SQL refund | correction-only exact stored month; shared helper/limits/config unchanged |
| Exact tenant purge | Child ordering | ledger/application before parent; foreign tenant and neighbors unchanged |
| UI/apply/editor/approval/domain/provider/worker/billing | None | no mutations outside existing correction draft apply, no new provider call |

Write scope:0178; correction_models.py, new correction_accounting.py,
correction_service.py; exact purge order; owned lifecycle tests and minimal isolated
gate wiring; canonical index/plan/changelog/errors as needed. Shared AI budget,
accepted0176/0177, UI, auth/roles, config/dependencies, queues, schedules, production
and public schema are forbidden writes. No PII or source bytes in evidence.

## Ready, checks, completion and stop

Ready: root accepts this impact after independent review; linked-write guard and
one writer; source-bound budget/DB policy map and canonical free DEV procedure.
Focused public behavior RED/GREEN: durable marker before provider, marker failure
no call, ready/refund exact once, role loss, original month, cancellation and
unknown commit; unchanged replay/apply. Migration/producer-consumer contracts
cover grants, guarded states and cascade. Actual random owned Supabase DEV:
empty/populated migration, legacy refusal to fabricate, original-month refund,
insufficient aggregate rollback, late completion/repeat, both tenants/ordinary/no
context denials, forged identities/month/time/state, dry-run, batch ordering/limits,
exact24h/90d boundaries, application receipt classification under maintenance RLS,
SKIP LOCKED/replay interleavings, removed-ID refusal, purge/neighbor invariants,
populated downgrade refusal and empty down/up. Cleanup/fresh absence and public
metadata neutrality mandatory; maximum3 connections, permanent QA untouched.

Done: focused/neighbor checks and owned runtime PASS, independent source and
frozen Runner accepted, sanitized receipts and exact Git readback; LOCAL_ONLY,
not assembled DEV/browser/provider-semantic/production GO. Stop and amend contract
on unlisted dependency, wider authority, billing/retention/data expansion, isolation
or cleanup failure, repeated access failure, or need to weaken any gate.

Pre-implementation review: cheap independent reviewer found3 P1 clarifications
(commit windows, DB month versus generic helper, explicit child purge ordering).
Amended source closed all3 on rereview; final P2 marker naming is resolved above
as provider_boundary_at, explicitly not invocation evidence. No product source
was written before this accepted impact. Later changes require versioned addendum.
