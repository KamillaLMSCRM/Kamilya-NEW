# Этап 3: замыкание корпоративного контура Kamilya

## Scope and truth

- Owner: root Codex agent; product owner: Kamilya owner.
- Repository and exact commit: `KamillaLMSCRM/Kamilya-NEW` at
  `967d15cd82a96bc863560769dc2a0e356acfea9f` (`v0.11.12`), clean worktree at
  bootstrap.
- Environments: local deterministic checks, isolated Supabase DEV, existing
  Kamilya DEV services, existing production synthetic tenant only.
- Last updated: 2026-09-28 Asia/Qyzylorda.
- Exclusions: customer tenant writes, provider plan/billing changes, DNS,
  production migration, production release without a complete exact packet,
  Kamilya landing and adjacent repositories.

| Claim area | Canonical source | Freshness / limitation |
|---|---|---|
| Product | `PROJECT.md` | Current product boundary; runtime identity is not stored here |
| Current system | `docs/PROJECT-CONTEXT.md` | Topology is canonical; dated SHA examples require fresh readback |
| Production | `docs/PRODUCTION_READINESS.md` | Must be reconciled with exact `0.11.12` runtime evidence |
| Open work | `docs/PRODUCT_BACKLOG.md` | Dated 2026-09-26; contains items already closed by `0.11.9`-`0.11.12` |
| Stage 0/1 outcome | `docs/product/CORPORATE_READINESS_MAP_2026-09-26.md` | Baseline only; capability statuses require current-release refresh |

Graphify was rebuilt from this exact candidate checkout with `graphify 0.9.58`
and `graphify extract . --code-only --max-workers 2`. The verified index contains
22,043 nodes and 50,707 edges; `graphify diagnose multigraph` reports zero
missing endpoints, dangling endpoints, self-loops or duplicate edges. Eleven
SQL files were not parsed because the optional `tree_sitter_sql` dependency is
not installed, so migration assertions still require direct source readback.
Cross-module navigation uses bounded Graphify queries followed by decisive
source/test confirmation.

## Observable objective

An authorized methodologist and learner complete one disposable corporate
training lifecycle on an exact deployed revision, and Kamilya returns the same
occurrence/enrollment truth through the mandatory-training matrix, dashboard,
training log, CSV/PDF/ZIP evidence and signed-copy workflow. A repeated
assignment preserves the first immutable history. Cleanup leaves no disposable
tenant records, files or jobs.

## Ownership

| Scope or operation | Owner | Writer | Reviewer | Overlap rule |
|---|---|---|---|---|
| Acceptance contract and task graph | root | root | root final review | No concurrent writer |
| Acceptance harness and focused tests | root | root | root diff/test review | No shared release-file edits during implementation |
| Local/DEV execution and evidence | root | none except exact disposable DEV fixture and authorized ledger append | root | No customer or persistent demo cleanup |
| Production synthetic browser/API acceptance | root | exact disposable objects in existing synthetic tenant | root | No customer tenant access |
| Release/Test Runner health | root | runner contracts/tests only if a reproducible defect exists | root | No production packet until no-mutation probe passes |
| Release, if required | root | deterministic controllers only | Test Runner plus root | Requires complete immutable packet and exact authorization |

## Dependency graph

`CR3-01 -> CR3-02 -> CR3-03 -> CR3-04 -> CR3-05`

`CR3-03 -> CR3-06 -> CR3-04`

`RUNNER-01 -> CR3-07`

`CR3-05 -> CR3-08`

## Nodes

### CR3-01 — Current acceptance contract and backlog reconciliation

- Status: `DONE`
- Scope: canonical product/readiness/backlog documents and machine-readable
  critical journey.
- Owner / writer: root.
- Dependencies: none.
- Exit gate: completed `0.11.9`-`0.11.12` items are removed from open backlog;
  one exact stage-3 journey and exclusions are canonical.
- Evidence: `GIT-DERIVED` current release notes, source and plans;
  `RUNTIME-DERIVED` fresh public API/frontend readback at exact `0.11.12`.
- Approval gate: `OWNER-CONFIRMED` by “Ок. Делай” on 2026-09-28.
- Cleanup / rollback: ordinary Git revert before release.

### CR3-02 — Deterministic contract baseline

- Status: `DONE`
- Scope: existing hierarchy, assignment, reassignment, learner completion,
  signed-copy, mandatory-training, training-log and evidence-export contracts.
- Owner: root; writer: none.
- Dependencies: CR3-01.
- Exit gate: named focused selectors pass through
  `scripts/dev/run_api_pytest.ps1`; frontend contracts pass through the
  repository package manager; zero-test runs fail the gate.
- Evidence: `TEST-DERIVED` command summaries and exact selectors.
- Result: focused API baseline `67 passed, 9 skipped`; focused frontend baseline
  `70 passed`; reassignment regressions `10 passed`; assignment UI `14 passed`;
  Ruff, ESLint and frontend typecheck PASS.
- Approval gate: not required; local read-only checks.
- Graph evidence: signed-scan upload resolves through
  `learner_attach_returned_signed_scan()` -> `append_signed_scan()`; accepted
  signed copies enter `build_individual_evidence_package()`; dashboard readback
  resolves through `dashboard()` -> `get_admin_dashboard()`. Source and tests
  remain the final authority for behavior.

### CR3-03 — Disposable corporate journey harness

- Status: `DONE`
- Scope: acceptance-only orchestration and tests; production application modules
  are unchanged unless a separately reproduced defect requires CR3-06.
- Owner / writer: root.
- Dependencies: CR3-02.
- Exit gate: the harness records sanitized per-stage timing, validates runtime
  identity, uses explicit environment/fixture boundaries, verifies fail/retry/pass,
  signed-copy review, evidence export, reassignment history and reconciliation,
  and guarantees cleanup in `finally`.
- Evidence: `GIT-DERIVED` diff plus `TEST-DERIVED` harness contracts.
- Approval gate: disposable DEV mutations only.
- Stop condition: any customer data dependency, direct DB repair, unbounded
  cleanup, or missing source-of-truth interface.
- Result: `scripts/ops/corporate_readiness_dev_acceptance.py` executes the
  machine journey contract only with explicit `--execute`, rejects zero-test
  runs, records stage timings and cleanup, and cannot target production.

### CR3-04 — Isolated DEV full journey

- Status: `DONE`
- Scope: exact disposable DEV data and existing free-tier services.
- Owner: root; writer: harness only.
- Dependencies: CR3-03 and CR3-06 when defects are found.
- Exit gate: terminal PASS for the complete journey; exact API/worker/frontend
  identities; reconciliation PASS; cleanup and residue PASS.
- Evidence: `RUNTIME-DERIVED` sanitized report and cleanup readback.
- Approval gate: owner-approved disposable synthetic data; no plan/billing
  change.
- Result: terminal PASS in `429.782s`: local contracts `10`, DEV DB contracts
  `9`, signed-copy RLS PASS, manual-reassignment RLS PASS, responsibility PASS,
  training-log `24`; every mutable gate cleanup PASS, zero customer writes and
  zero provider/billing changes.

### CR3-05 — Production synthetic human acceptance

- Status: `BLOCKED`
- Scope: existing production synthetic tenant only, exact deployed revision,
  browser plus bounded API readback.
- Owner: root; writer: exact disposable synthetic objects.
- Dependencies: CR3-04.
- Exit gate: methodologist and learner journeys pass at 1440/1024/390 px;
  matrix/dashboard/log/export/evidence reconcile; no new browser/API errors;
  cleanup PASS.
- Evidence: `RUNTIME-DERIVED` exact revision, timing ledger, browser/API
  readback and sanitized screenshots where useful.
- Approval gate: owner-approved stage-3 plan; no customer tenant or provider
  mutation.
- Runtime finding: exact `0.11.12` synthetic tenant login, dashboard, staff
  structure, course selection, retained completed history and reassignment
  reason UI passed. The final reassignment POST reproduced HTTP `409`
  `Assignment link policy must be extended before reassignment` for a retained
  absolute-only access policy. Candidate repair is complete under CR3-06; this
  node resumes only after exact release promotion.

### CR3-06 — Minimal repair loop

- Status: `DONE`
- Scope: only a defect reproduced by CR3-02/CR3-03/CR3-04.
- Owner / writer: root.
- Dependencies: a stable RED with classified layer.
- Exit gate: minimal fix, focused RED/GREEN, neighbor regression, ERRORS update
  for a recurring class, same failed stage repeated.
- Approval gate: source changes within the accepted objective; migrations,
  billing, provider configuration and scope expansion stop for owner decision.
- Result: historical positive windows are recovered from the latest provable
  policy timestamp without changing predecessor evidence; unprovable policies
  remain fail-closed. The UI displays the canonical API `message`. RED/GREEN,
  neighbor regression and complete DEV journey PASS; `ERRORS.md` updated.

### RUNNER-01 — Release/Test Runner no-mutation health

- Status: `DONE`
- Scope: persistent runner contracts, exact-checkout routing and executor
  capability classification.
- Owner / writer: root.
- Dependencies: none.
- Exit gate: a fresh no-mutation probe cannot complete empty, reads the exact
  checkout, keeps DEV away from CT137/SSH and reports executor failure without
  misclassifying provider credentials.
- Evidence: `TEST-DERIVED` runner contracts and, when callable, task readback.
- Approval gate: no production packet; no external mutation.
- Result: persistent Test Runner passed the exact 35-test checkout contract;
  persistent Release Runner rejected an incomplete packet without controller,
  deployment or repository mutation.

### CR3-07 — Release candidate and promotion, only if code changes

- Status: `READY`
- Scope: exact candidate built from completed stage-3 repairs.
- Owner: root; writer: deterministic release controllers.
- Dependencies: CR3-04, RUNNER-01 and complete release packet.
- Exit gate: full risk-based candidate suite, DEV exact-SHA acceptance,
  immutable packet, CI, synchronized runtime and separate Test Runner product
  acceptance.
- Blocker / next action: application and frontend repairs now require one exact
  immutable release packet and release authorization before DEV/prod promotion.
  No migration, billing or provider change is required.

### CR3-08 — Canonical documentation closeout

- Status: `NOT_STARTED`
- Scope: `PRODUCT_BACKLOG.md`, corporate readiness map,
  `PRODUCTION_READINESS.md`, testing ledger when ownership is granted.
- Owner / writer: root except append-only Test Runner ledger ownership.
- Dependencies: CR3-05.
- Exit gate: durable facts replace stale statuses; residual risks and next epic
  are explicit; this temporary task graph is removed after transfer.

## Decisions and approvals

| ID | Decision or exact approved mutation | Evidence | Owner | State |
|---|---|---|---|---|
| CR3-D01 | Execute the agreed stage-3 plan and use only synthetic contours | `OWNER-CONFIRMED` 2026-09-28 “Ок. Делай” | Kamilya owner | USED |
| CR3-D02 | Do not mutate customer tenants or provider billing/plans | workspace/project policy | Kamilya owner | OPEN |
| CR3-D03 | A production release requires a complete exact immutable packet | `AGENTS.md` and runner contract | root | OPEN |

## Completion gate

- [ ] Required nodes satisfy their exit gates.
- [ ] `BLOCKED` nodes have an accepted external condition and next owner.
- [ ] No overlapping writer or unreviewed external mutation remains.
- [ ] Cleanup and residual-state audit pass.
- [ ] Durable facts moved to canonical documentation.
- [ ] Temporary task graph removed after transfer.
