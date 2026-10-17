# Transfer preservation and legacy write guards

Status: Accepted for DEV implementation. Version: V1, 2026-10-17.
Approved by: Root, technical scope under current owner DEV request.
Amends EPIC_V1; source evidence from independent reviewer and Root source reads.

Existing recompute later deletes obsolete noncompleted managed enrollments. Retaining
them only during transfer is insufficient. Add tenant-scoped preservation markers
keyed by enrollment ID, original source and optional plan ID. They live as long as
their enrollment; plan purge must not remove the protection. RLS+FORCE RLS and
cross-tenant tests are mandatory. Recompute skips marked obsolete rows, preserving
provenance and existing progress. Completed/manual/cohort/program rows are never
rewritten. Marker is not a new assignment source or a qualification/compliance flag.

Additional explicit impact: positions/router.py, users/staff_import_service.py,
staff_import_sessions/commit_service.py and staff_sync/service.py must reject legacy
placement changes in the enabled DEV contour instead of bypassing preview. Position
assign/unassign or department moves require the new reviewed flow; unchanged metadata
and new-record creation stay available. Generic imports may create records but cannot
silently relocate existing employees or move existing organizational entities. Fail
the transaction, do not partially skip rows or reactivate inactive existing users.
Non-student existing identity matches cannot be overwritten by generic staff import.
No production behavior changes because the contour opt-in defaults disabled.

Existing dormant StaffSyncIdentity/Event storage already maps tenant/source/external
employee ID and event idempotency. Future 1C should extend that interface, not add a
duplicate external-ID field on User. Snapshot HR ownership includes these identities;
manual transfer of linked employees is blocked. Future unit/position namespace and
effective-version/conflict rules still need a connector-specific contract. No active
1C connector, credentials, external calls, HR-status or login transitions are added.

Ownership: Root owns all these guards, preservation schema and enrollment kernel;
frontend worker's write set unchanged. Tests include later recompute survival,
legacy bypass rejection, unchanged/new import paths, dormant-sync rejection,
rollback after late conflict, and cross-tenant marker isolation. Any further module
impact requires another accepted addendum before editing.
