# Readable impact details

Status: Accepted, 2026-10-17. Root technical approval within DEV scope.
EPIC_V1 remains preserved. This additive response extension does not change policy.

Workspace positions additionally expose `employee_count` (company-wide within the
selected account filter) and `unit_counts` (effective-unit UUID keys or `unplaced`).
Position detail shows positions actually held in the selected direct/subtree
population, not merely Position.department_id; disclose cross-unit reuse.

Preview training additionally exposes `courses:[{course_id,title,added,
retained_previous}]`, grouped from exact user-course additions and removed effective
requirements. All existing enrollments remain unchanged. `retained_previous` counts
old assigned courses losing requirement, not deletion. The confirmation screen must
show course titles/counts as well as aggregate training/reporting counts.

Preservation protections apply to ordinary recompute DELETE and source UPDATE even
when the new UI/change flag is disabled. UI-only rollback can hide the new workspace;
do not roll back to a pre0182 enrollment kernel with retained markers present.
Before rolling back such backend code, restore/remove only the owned synthetic test
changes or retain the marker-aware kernel. No deletion of real learning is authorized.

Invalid commands map422, stale/expired/managed/serialization409, unknown/oversized
impact503, foreign resources404. Unknown errors do not echo internal payloads.
