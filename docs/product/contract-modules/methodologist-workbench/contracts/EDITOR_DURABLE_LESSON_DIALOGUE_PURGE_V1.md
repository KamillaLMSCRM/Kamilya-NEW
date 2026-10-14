# Dialogue populated tenant purge impact V1

Accepted by Root 2026-10-14 before neighboring edit. Addendum to durable dialogue
V1. Source inspection confirms SuperadminService uses an explicit table list,
not automatic discovery of all tenant-scoped tables. Add the new dialogue table
before lessons in TENANT_DELETE_SQL; preserve all existing order, guards and
exact tenant/slug authority. The table's tenant-scoped superadmin DELETE policy
allows this existing owner, never an ordinary methodologist. FK cascade remains
compatible with the prior application, whose purge already deletes lessons.

Root write scope additionally includes that one statement in
apps/api/app/modules/admin/superadmin/service.py and its focused purge contract
regression. No new privileges/functions/role changes or unrelated cleanup.
Require scoped populated deletion, sibling preservation, no-context/ordinary
DELETE negatives, source ordering test and existing purge regressions. UI and
archive ownership are unchanged; no test tenant or production deletion implied.
