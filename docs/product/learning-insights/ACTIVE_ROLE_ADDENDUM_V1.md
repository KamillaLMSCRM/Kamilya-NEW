# Active-role alignment

Accepted by root, 2026-09-06, to comply with existing ADR-0012 and routeRegistry.
This corrects an overbroad root assumption in EPIC_V1; it does not amend RBAC.

Learner-level results and their follow-up decisions belong only to the active
methodologist role, with an exact tenant context. Both new API and UI guards
require that role. Admin, student and active superadmin are denied, even when
a tenant identifier is present. Platform operations use existing authenticated
impersonation into an authorized methodologist context, not a new bypass.

The original EPIC and DTO examples allowing a tenant-bound superadmin directly
are superseded on that specific point. No route registry, permission union,
session switching, login, or existing export permissions are broadened.
Read and write negatives cover all non-owning active roles; same-role foreign
tenant objects remain 404. The authenticated impersonation actor remains nullable
in the annotation FK because the underlying platform account is not a tenant user.

Evidence: a full-journal render with active superadmin is denied by the existing
canonical route guard; a helper-only role mock had incorrectly suggested otherwise.
Keep the full-page role test alongside the component and real API/RLS tests.
