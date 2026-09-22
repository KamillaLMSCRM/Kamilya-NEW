# Repeat assignment and learning analytics plan

## Goal

Add an explicit methodologist-owned repeat-assignment workflow that creates a
new immutable enrollment occurrence while preserving the previous enrollment,
quiz attempts, progress, release evidence, certificate and returned evidence.
Make operational dashboards count only current/actionable occurrences while the
training log can deliberately include historical occurrences.

## Public seams confirmed by the owner

1. `POST /api/v1/courses/{course_id}/reassignments` is the only mutation seam
   for manually repeating a course for one learner.
2. `/assignments` exposes the action and requires a reason before submission.
3. `/api/v1/admin/training-log` exposes current and historical occurrences with
   an explicit history filter; `/training-log` renders the lifecycle honestly.
4. `/api/v1/admin/training-log/summary` and `/dashboard` expose current learning
   operations and outcome metrics without counting cancelled/superseded history
   as active work.
5. Production acceptance uses only the synthetic production tenant and verifies
   methodologist action, learner isolation, retained old attempt history, reset
   new-attempt allowance and dashboard/journal readback.

## Invariants

- A completed enrollment is never mutated or reopened.
- Every repeat creates a new enrollment ID and binds the current content release.
- The previous enrollment remains readable evidence and is linked to the new one.
- Open previous manual enrollment becomes `superseded`; completed history remains
  `completed`; cancelled history remains `cancelled`.
- Repeating rule-driven enrollment is rejected; its owner workflow is the rule or
  recurring-cycle domain.
- Attempt limits are enrollment-scoped, so the new occurrence starts at zero.
- Tenant ownership is enforced in API, database trigger/RLS and cross-tenant tests.
- Operational totals exclude `cancelled` and `superseded`; history views include
  them only when explicitly requested.
- Tenant admin does not gain learning-result access; methodologist owns the flow.

## Vertical TDD slices and acceptance

- [x] Slice 1: repeat-assignment API creates one linked occurrence and preserves a
  completed predecessor unchanged; active predecessor becomes superseded.
- [x] Slice 2: invalid source, foreign tenant, foreign learner, draft course and
  stale predecessor conflicts fail without partial writes.
- [x] Slice 3: migration adds linkage/reason/audit fields, ownership validation,
  runtime grants, RLS/FORCE RLS compatibility and safe downgrade refusal/history.
- [x] Slice 4: assignment UI requires a reason, calls the new seam, refreshes the
  course assignments and explains that history is preserved.
- [x] Slice 5: training log distinguishes current, completed, cancelled and
  superseded occurrences and offers current/history filtering.
- [x] Slice 6: dashboard summary exposes active, not-started, in-progress,
  completed, overdue, failed-current, exhausted-attempt and reassigned counts;
  cancelled/superseded history cannot inflate current totals.
- [ ] Slice 7: focused API/web tests, complete local no-DB/API/web regression,
  canonical Supabase DEV migration/RLS/integration checks and browser acceptance.
- [ ] Slice 8: version/changelog/release notes, exact-SHA CI and protected release,
  production DB/image/frontend readback, synthetic live journey and rollback proof.

## Production stop conditions

- Any cross-tenant visibility or mutation.
- Any mutation of the previous quiz attempts/evidence/completion.
- Migration head mismatch, missing runtime grant, RLS/FORCE RLS regression or
  restore-drill failure.
- Dashboard and training-log totals disagree for the same explicit filter.
- Exact API, worker and frontend revision cannot be independently read back.
- Synthetic journey cannot prove both retained history and a clean new occurrence.
