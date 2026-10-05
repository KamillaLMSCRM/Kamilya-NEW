# WB-LESSON-CORRECTION-PREVIEW V1.4

Accepted database clock authority impact, root/module owner, 2026-10-05.
Preserves V1..V1.3 and DEV validation V1/V1.1. Runtime C passed source and metadata
roundtrip then admission failed SQLSTATE23514. Canonical read-only clock probe
proved the application clock ahead of DEV PostgreSQL by0.745..1.048s. Computing
expiry from application time can exceed DB-created_at+15minutes. Do not relax
the lifetime check or change machine/database clocks.

Extend root scope to correction_service.py and its existing focused service test.
Sample PostgreSQL clock_timestamp() in the owned runtime transaction for snapshot
created_at, expires_at and ready/render foundation time checks. Sampling precedes
INSERT; the existing trigger still sets immutable row-created_at from DB clock.
Snapshot/row expiry remain equal and bounded, no new fields or migration. Require
an aware returned datetime, refuse unavailable clock with fixed conflict; never
fall back to host time. A preview is still15minutes maximum, not a duration promise
extended by network or generation latency.

Monthly shared accounting remains unchanged: existing pre/post host-UTC month
guards compare to DB-admission month and conservatively refuse/refuse refund when
months disagree. No unapproved shared budget helper changes or blind restart.
Same-month skew should not reject a valid preview; true cross-month accounting
uncertainty remains pending/reconciliation gate.

RED/GREEN public create/read behavior must prove exact DB-derived timestamps
under an ahead host clock. Adjust the existing fake only for this actual SQL
interface; mocks remain local test boundaries, not runtime proof. DEV month-clock
sequences must follow the new sample seam and prove real rollback/reservation.
Require successor owned runtime evidence with unchanged0176 guards, then local
and independent source/quality acceptance. No public schema/flags/provider/production
activation or apply/UI authority is added.
