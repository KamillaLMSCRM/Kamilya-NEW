# Continuation safety addendum V1

Status: Accepted. Approved by: Codex root, 2026-09-30.
Supersedes: the LRN continuation eligibility clause in EPIC_V1.md; other clauses remain active.
Reason: independent source review confirmed the existing course player resolves
the newest open current occurrence rather than accepting an arbitrary enrollment ID.
No production authority or new module boundary is granted.

## Contract and impact

The additive learner response includes `can_resume: bool` (default true for older
consumer fixtures). Default dashboard results order occurrences exactly like
`current_enrollment`: open before completed, then enrolled_at descending, then
enrollment ID descending. Only that canonical delivery occurrence per course
receives `can_resume=true`. Other current same-course occurrences remain visible,
but do not compete for the next-course recommendation and do not expose a start/
continue link. The learner sees an explanation to ask their methodologist for an
assignment-specific access route. No arbitrary lesson is suggested for a different
delivery occurrence; no token is prefetched or new access issued.

Personal-link restricted identity remains restricted to its authorized enrollment;
this additive read model does not widen access. Existing player/progress/quiz/SCORM
API contracts are unchanged. A future occurrence-aware player is a separate contract.

Verification: two overlapping same-course occurrences with different deadlines/
progress; canonical selector tie-break; only selected occurrence eligible; older
occurrence visible without link. SQL progress correlation and no N+1 remain required.
Rollback is the same feature revert; there is no data migration.
