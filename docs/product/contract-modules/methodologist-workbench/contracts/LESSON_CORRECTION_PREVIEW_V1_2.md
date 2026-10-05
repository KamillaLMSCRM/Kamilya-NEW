# WB-LESSON-CORRECTION-PREVIEW V1.2

Accepted local accounting-safety addendum, 2026-10-05, root/module owner;
same preview scope. Preserves V1/V1.1 except the bounded month behavior.

The existing shared charge/refund helper uses the current UTC calendar month
and has no request receipt. Do not change that helper or invent exact provider
cost accounting. Admission verifies that the snapshot month, time immediately
before the shared charge and time immediately after it agree; otherwise the
claim and charge are rolled back before any provider request.

Failure closure compares current UTC month to the admitted snapshot month while
holding the owned pending-record lock and again after the shared refund, before
commit. A mismatch rolls back closure/refund, leaves the record pending and
returns a fixed correction conflict, rather than refunding another month's
usage. Replays do not restart/charge/refund it. Cancellation still propagates.
Crash/cross-month reconciliation remains a future explicit accounting gate and
must be resolved before public activation. Successful ready proposals can finish
across a month boundary; their estimate remains in the admission month.

No provider, configured budget, price, resources, extra table column, domain write
or rollout authority changes. Test month-boundary admission rollback/no provider
and pending failure/no wrong-month refund locally; actual atomicity is a DEV gate.
