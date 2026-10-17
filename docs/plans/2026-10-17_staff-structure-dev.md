# Staff structure DEV integration

Root owns integration and acceptance. Baseline50d3a426482ca08a5a5b003337752251eb02c375
in methodologist-video-guide-20261016 linked checkout. Existing authoring docs and
experiments preserved. Owner authorizes DEV only; production, voice/reserve, billing,
customer data and 1C connector activation excluded.

Contract: ../product/contract-modules/staff-structure/EPIC_V1.md.
Sources: PROJECT.md, PROJECT-CONTEXT.md DEV map, ERRORS STAFF-UI001–003/DEV-SCHEMA001,
ADR0024/25. Navigation preflight NOT_READY: missing checkout-local CodeGraph runtime;
Graphify graph absent. Bounded source fallback, not runtime proof.

`S1 inventory -> S2 contract -> (S3 backend, S4 frontend) -> S5 integration/review -> S6 DEV`

| Node | Owner/writer | State | Exit gate |
|---|---|---|---|
| S1 inventory | Root + two read-only workers | DONE | exact source seams and current checkout |
| S2 contract | Root | DONE | accepted V1, additive training, no auth-policy mutation, 1C exclusions |
| S3 backend | Root | DONE_LOCAL | policy/service73 + real isolated Supabase25; public DEV not changed |
| S4 frontend | bounded worker / Root | IN_REVIEW | schema/roster/preview; final ambiguous-confirmation reload recovery underway |
| S5 integration | Root / independent reviewer | IN_PROGRESS | final full suite/build/review; DEV controller V6 local tests |
| S6 DEV | Root | NOT_STARTED | existing-tier deployment, exact readback, ordinary-role live flow, cleanup |

One writer per path. Root owns routes/migration/shared auth/legacy guard and staff
page integration. Frontend worker owns new StaffWorkspace* files and named tests
only. Reviewers read only. No subagent external access or nested workers.

Approval: current owner request authorizes this DEV integration and synthetic tests;
never production. No provider plan/resource additions. Fresh actual provider identity
and unchanged tier gate before deployment; rollback previous DEV revision and disable
new feature, retain additive schema. Existing DEV branch has unrelated commits and
must be preserved, not reset to master. No completion claim until S6 passes.

2026-10-17 owner adds optional1C HR compatibility. Accepted design addendum:
HR_COMPATIBILITY_ADDENDUM_V1.md. Existing StaffSyncIdentity/Event reused; no live
connector, HR status field or multi-employment support claimed. Clients without
integration retain ordinary manual/import workflow; no HR configuration clutter.

RUNTIME-DERIVED: isolated-08.json in ignored .release-evidence/staff-structure-dev
PASS25checks, source-hash-bound, exact owned-schema cleanup and public catalog neutral.
Includes real serializable double-confirm, competing assignment insert, late-flush
rollback, provenance retention after receipt purge, actor/tenant RLS and unit move.
Neighbor RLS is synthetic, not a full public-policy acceptance. Earlier harness
failures preserved in isolated01–07, not overwritten/relabelled. No public DEV writes.

GIT-DERIVED: fresh project-account fetch confirms origin/master=50d3a426 baseline;
origin/dev=b35d11a2, HEAD...dev diverges1/15; preserve both histories. No push yet.
Local Python quality baseline PASS without debt relaxation; full offline suite first
run3148PASS/1FAIL missing canonical model registration, corrected and focused2PASS;
final full rerun pending. Feature-on web page integration found unauthorized mappings
and session-restore fetches; guarded by active methodologist role, four-file27PASS.
First feature-on build found nullable selected-unit copy bug, fixed; rebuild pending.
