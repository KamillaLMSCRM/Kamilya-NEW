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
| S3 backend | Root | DONE | full API3334; real isolated Supabase25; public0183 applied |
| S4 frontend | bounded worker / Root | DONE_LOCAL | web1191; feature-on build67/67; explicit ambiguous-confirm recovery |
| S5 integration | Root / independent reviewer | DONE | source-GO32ff120f, quality/build/PR CI PASS; preserved DEV/runtime0182 |
| S6 DEV | Root | PARTIAL_INFRA_BLOCKED | functional browser/cleanup PASS; final worker parity blocked after two network timeouts |

One writer per path. Root owns routes/migration/shared auth/legacy guard and staff
page integration. Frontend worker owns new StaffWorkspace* files and named tests
only. Reviewers read only. No subagent external access or nested workers.

Approval: current owner request authorizes this DEV integration and synthetic tests;
never production. No provider plan/resource additions. Fresh actual provider identity
and unchanged tier gate before deployment; disable new UI/writes but retain the
marker-aware enrollment kernel and additive schema while preservation facts exist.
Do not blindly revert to the older b35 kernel. Existing DEV branch has unrelated commits and
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

2026-10-17 current checkpoint supersedes pending local gates above:
- Preserving merge32ff120f47d385b58a0cc5cbf20dae6083404fe2 retains both50d3 master
  and b35d11a2 DEV histories. Staff revision0183 follows existing runtime0182;
  SCHEMA_COORDINATION_ADDENDUM_V1 is the accepted correction, not rewritten history.
- Canonical offline API3334PASS, full web1191PASS across164files, feature-on build
  67/67, Python quality PASS with no debt allowances. Initial unrelated1s journal
  timeout under concurrent load passed focused and full two-worker rerun; assertions
  and timeout unchanged. Release contract linear181 revisions, head0183.
- Current isolated-10-0183 PASS25 with exact source hashes, cleanup and public
  catalog neutrality; runtime0182 isolated dependency PASS17/cleanup/neutrality.
  Independent reviewer recomputed current hashes and confirmed SOURCE-GO after merge.
- Draft PR17 targets dev, CI39006967348 SUCCESS exact32ff. Both project-account
  feature and dev pushes independently read back32ff; sanitized receipts retained.
- Public DEV gate applied only0182->0183, exact pinned DEV project hash verified.
  V6 prepare CONFIGURATION_READY: only staff api/worker/frontend flags false->true;
  old workbench/document/correction flags preserved true. Free/Free/Hobby unchanged.
- Exact V6 REL-DEV-STAFF-STRUCTURE-20261017-001 execute in progress; push CI39007554649
  pending at this checkpoint. No claim of exact provider rollout or live acceptance.
- Existing ordinary QA methodologist login and baseline staff screen verified;
  no public business fixture writes yet. Production/master/voice/reserve unchanged.

Subsequent live checkpoint: V6 exact32ff RELEASE_OK; see TEST_RUN_LEDGER for
provider IDs and two owned success plans. Employee/unit moves, reload, direct/
subtree, keyboard tabs and shared-position counts PASS. Only one owned employee
and two owned units created, no email/phone/credential/new position. Cleanup open.
Live1280x720 found compact side-card overlap and generic cycle error copy;
STAFF-UI-004 records both. Bounded frontend repair reviewed by Root, focused28 /
typecheck/scopedlint and full web1201PASS. Build and no-config DEV follow-up pending;
API/schema/policy unchanged, so current source-bound isolated25 evidence retained.

Final checkpoint2026-10-17:
- UXab4a6d7e/full web1201/build67 passed. CI39008666487 exposed Root's invalid
  journal field label, not API behavior: changed Fix scope->Fix, exact contract
  gate/reliability2PASS; new docs-onlyda21bb3b preserves identical tested UI/API.
- FinalCI39008984682 SUCCESS. API/webda21 live/READY; public schema0183; existing
  Free/Free/Hobby and four feature-flag inventories verified unchanged after opt-in.
- Workerda21 dep-db9h6mvavr4c73e2do3g then one exact retrydep-db9h85jbc2fs73dpc2j0
  both update_failed, fixed logcode ssh_start_failed_network_connect_timeout.
  Old32ff worker retainedlive/healthok. No third retry, no key/SSH/port/model/tier
  mutation. Final release BLOCKED_WORKER_PARITY; source/functional PASS is separate.
- Live repaired narrow card/single heading and primaryCTA/canonical cycle error,
  import access PASS. Rename ownedA->A2 in second tab invalidated old employee plan
  024d6813-c6e3-4d3a-b3ac-074ce6f9fb9e; rejection made no transfer. Fresh plan
  00fcbd34-4228-4546-a46d-c148e1baf31d succeeded B->A2; reload retained placement.
- Ordinary UI terminated only personnelQA-ORG61-20261017. Ordinary API soft-archived
  B thenA2 after exact identity/empty/no-head/no-active-position checks. Archive
  readback PASS, old units/position catalog equal, original active roster3.
  Audit and one inactive employee/two archived units remain, no hard purge claim.
- Before production: restore discoverable archive controls in the new workspace,
  distinguish/filter archived units on cards, deduplicate stale-message copy;
  assess bounded large-company performance. Production and live1C remain excluded.
  Deterministic receipts/screenshots: .release-evidence/staff-structure-dev.
