# Lesson correction lifecycle V1.1: locked action provenance

Status: Accepted for LOCAL + owned synthetic DEV, 2026-10-05, before product repair.
Root is integration/migration owner; independent bounded reviewer confirmed the
source-level P2. Owner's approved lifecycle scope is unchanged; V1 stays immutable.

## Defect and required result

The maintenance candidate query's joined accounting state is a selection snapshot,
not proof of the transition subsequently performed. Under READ COMMITTED a T2
marker can commit between that snapshot and acquisition of the parent lock. Even
with SKIP LOCKED, a row already unlocked at visitation can carry an older joined
reserved state. The fresh accounting lock can correctly settle started->retained
but a stale candidate action can incorrectly report reconcile_refund.

Apply must derive the returned action from the freshly locked accounting row,
not its joined candidate snapshot: reserved means reconcile_refund; started or
legacy/no record means reconcile_retain; terminal/malformed remains a refusal.
The dry-run remains a point-in-time estimate and acquires no row locks.
Deletion classification, timestamps, tenant/RLS/ACL, budgets, refund predicates,
parent-first order, batch/retention, no provider retry and all V1 protections stay
unchanged. This is output correctness, not evidence of an unsafe refund.

## Write and verification scope

Only0178 maintenance return-action assignment; static migration/gate tests;
owned lifecycle driver/checks and canonical index/plan/changelog/errors. No shared
budget, predecessor migration, UI, role, limit, provider, public or production write.

Add actual owned marker/maintenance interleaving: hold a legitimate uncommitted
T2 start marker across expiry; candidate cursor takes its snapshot; an earlier
owned parent's fixture trigger establishes readiness and waits through a bounded
nonblocking advisory poll; commit T2 before target visitation; release/drain the
maintenance task. Runtime guards remain enabled, maximum3 connections and all
statement/lock/overall limits unchanged. Assert both retained terminal state and
returned reconcile_retain. No function-body mock or product-function replacement.
Preserve a genuine RED if reproduced; a fixture/timeout failure is not product RED.
Finally release/drain before exact schema cleanup and require public neutrality.

Repeat the final owned full matrix against frozen current sources and independent
local source/test acceptance. Prior C32/C1/C2/C3 artifacts remain historical; no
public release acceptance is inferred. Stop on failed isolation/cleanup, need to
weaken a limit, broaden scope or alter authority/billing/retention.
