# Generic import result counts repair V1

Accepted technical DEV repair2026-10-19, first-four-blocks import acceptance.
Root/module owner root, human product owner. Production remains excluded.
Live corrected XLSX created one branch and one department but the persisted result
reported branches_created0 and organization_units_created2. Cause: generic type
pluralization constructed branchs_created/branchs_updated, which do not exist in
the legacy result schema. Data creation and corrected placement succeeded.

Keep the existing result schema and counts ownership. For generic branch events,
increment branches_created/branches_updated and the generic organization counter
exactly once; department legacy totals remain accurate. Other generic unit types
increment only supported aggregate counters, not invented response keys. No
historical receipt rewriting, placement/training changes, migration or new endpoint.

Gates: tests execute the real async commit loop for branch and department creation
and update, fail before repair, pass after it. Fresh DEV import/reloaded receipt
must match independently read observed unit changes. Preserve prior failed/inaccurate
historical receipt as evidence; do not relabel it as corrected.
