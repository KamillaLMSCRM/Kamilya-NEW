# Source actuality and controlled retraining

## Scope and truth

- Owner: root Codex agent; product owner: Kamilya owner.
- Repository and exact baseline: `KamillaLMSCRM/Kamilya-NEW` at
  `123718aacd9d4d743fdb87cc6b5d70b84cb3501d` (`v0.11.13`), clean isolated
  worktree `C:\Kamilya New\.worktrees\source-actuality`.
- Environments/providers: local deterministic checks, isolated Supabase DEV,
  existing free-tier Kamilya DEV; production requires a later exact immutable
  release packet and fresh owner authority.
- Last updated: 2026-09-28 Asia/Qyzylorda.
- Exclusions: customer tenant writes, automatic publication, automatic
  retraining without a methodologist decision, provider billing/plan changes,
  DNS, landing, EDS/attestation/admission and adjacent repositories.

| Claim area | Canonical source | Freshness / limitation |
|---|---|---|
| Product | `PROJECT.md` | Corporate LMS boundary is current |
| Current system | `docs/PROJECT-CONTEXT.md` | Environment topology; runtime identity still needs fresh readback |
| Production | `docs/PRODUCTION_READINESS.md` | `0.11.13` closeout is node SA-00 |
| Open work | `docs/PRODUCT_BACKLOG.md` | Source ownership/change impact is the selected next epic |
| Architecture navigation | Graphify index in exact `0.11.13` worktree | 22,043 nodes / 50,707 edges; SQL parser gap remains |

## Ownership

| Scope or operation | Owner | Writer | Reviewer | Overlap rule |
|---|---|---|---|---|
| Product contract, migration, shared wiring and canonical docs | root | root | independent reviewer plus root | No agent edits these paths |
| Backend actuality/impact/decision module and focused tests | backend worker | one bounded worker | root | No frontend or shared-doc edits |
| Documents/course UI, localization and focused web tests | frontend worker | one bounded worker | root | No API/migration edits |
| Integration, DEV, release packet and runtime readback | root | root/controllers | Test Runner plus root | No worker external mutation |

## Dependency graph

`SA-00 -> SA-01 -> SA-02 -> SA-03 -> SA-05 -> SA-06`

`SA-01 -> SA-04 -> SA-05`

## Nodes

### SA-00 — Close corporate-readiness stage 3

- Status: `DONE`
- Scope: canonical readiness/map/backlog transfer and removal of the temporary
  stage-3 graph after durable facts are preserved.
- Owner / writer: root.
- Dependencies: none.
- Exit gate: `0.11.13` production human acceptance and residual runner gaps are
  accurately reflected; no stale `BLOCKED` stage-3 claim remains.
- Evidence: `RUNTIME-DERIVED` exact `0.11.13` assignment/reassignment acceptance.
- Approval gate: not required; documentation only.
- Cleanup / rollback: ordinary Git revert.
- Result: exact `v0.11.13` release identity, production reassignment acceptance,
  preserved completion history and the residual runner/readback limitations are
  recorded in canonical readiness/backlog documents; the superseded temporary
  stage-3 graph was removed.

### SA-01 — Source actuality contract and persistence

- Status: `DONE`
- Scope: tenant-scoped source-family policy, immutable revision review and
  change-decision records; API schemas and migration/RLS contract.
- Owner / writer: root.
- Dependencies: SA-00.
- Exit gate: RED/GREEN public-contract tests; additive single-head migration;
  tenant ownership, FORCE RLS and cross-tenant negatives.
- Approval gate: DEV migration only after local migration checks; production
  migration is not authorized by this plan.
- Cleanup / rollback: migration downgrade in isolated DEV schema.
- Result: additive revision `0165` is applied to Supabase DEV; isolated
  upgrade/downgrade, FORCE RLS, owner eligibility, immutable resolution,
  cross-tenant and cleanup/readback gates passed.

### SA-02 — Deterministic change-impact analysis

- Status: `DONE`
- Scope: compare original old/new revisions through the production-shaped
  converter and Evidence V2 source-fact adapter; reconcile removed/added facts
  with dependent lessons and their assessments.
- Owner / writer: backend worker.
- Dependencies: SA-01.
- Exit gate: deterministic fixtures prove added/removed/unchanged facts,
  impacted courses/lessons/questions, bounded failure states and tenant scope;
  no generative provider call is required.
- Approval gate: none for local synthetic fixtures.
- Cleanup / rollback: ordinary Git revert.
- Result: the production direct-source converter and Evidence V2 fact adapter
  compare only the latest active revision; added, removed, changed and unchanged
  facts are bounded and mapped to dependent courses, lessons and assessments.

### SA-03 — Methodologist decision and controlled draft/retraining handoff

- Status: `DONE`
- Scope: resolve an impact as no-learning-impact, update-future,
  update-and-retrain or suspend-old-assignment; preserve prior releases and
  completed enrollments; never publish or reassign implicitly.
- Owner / writer: backend worker; root owns enrollment/publication integration.
- Dependencies: SA-02.
- Exit gate: idempotent audited decisions, immutable predecessor evidence,
  derived draft source linkage and explicit next action; negative RBAC/RLS and
  stale-review conflict tests pass.
- Approval gate: no production/customer mutation.
- Cleanup / rollback: delete disposable DEV objects through public interfaces.
- Result: all four decisions are tenant-scoped and idempotent; update decisions
  create a separate reviewable draft, preserve published releases and completed
  history, and never publish or reassign automatically. Impacted quizzes use the
  existing `needs_review` database contract.

### SA-04 — Methodologist UX and action visibility

- Status: `DONE`
- Scope: document catalogue actuality state, owner/review dates, revision impact
  panel, decision dialog and course warning; RU/KK/EN, desktop/mobile and honest
  loading/error/empty states.
- Owner / writer: frontend worker.
- Dependencies: SA-01 API contract.
- Exit gate: focused UI contracts and accessibility checks prove all decision
  states without exposing IDs or claiming automatic publication/retraining.
- Approval gate: none for source changes.
- Cleanup / rollback: ordinary Git revert.
- Result: the documents page exposes owner/review policy, current revision,
  bounded impact and explicit decision controls in RU/KK/EN. Missing review
  dates stay empty rather than being invented by the browser.

### SA-05 — Integrated local and isolated DEV acceptance

- Status: `DONE`
- Scope: focused and neighbor suites, migration upgrade/downgrade, Supabase
  DEV/RLS and one synthetic revision-1 to revision-2 human journey.
- Owner / writer: root; disposable DEV fixture only.
- Dependencies: SA-03 and SA-04.
- Exit gate: exact candidate PASS, cleanup/residue PASS, Graphify update plus
  source/test confirmation, no customer/provider/billing mutation.
- Approval gate: existing owner authorization for synthetic DEV work; stop if
  any paid resource or customer data becomes necessary.
- Cleanup / rollback: harness `finally` cleanup and schema removal/readback.
- Result: focused API `26 passed`; complete API `2914 passed, 503 skipped`;
  frontend focused `3 passed`, complete frontend `711 passed`, typecheck, lint
  and production build passed. The transactional Supabase DEV journey passed
  through revision admission, production-shaped conversion, impact, methodologist
  decision, draft/lesson/quiz review states and cross-tenant `404`. Graphify was
  refreshed to 20,889 nodes / 49,988 edges with zero dangling or duplicate edges;
  SQL parsing remains unavailable and is not used as migration evidence.

### SA-06 — Release and production synthetic acceptance

- Status: `BLOCKED`
- Scope: exact immutable release packet, DEV promotion/readback, production
  rollout and synthetic browser acceptance.
- Owner / writer: root/controllers.
- Dependencies: SA-05.
- Exit gate: exact-SHA CI/artifact/API/workers/frontend/DB readback and a bounded
  production synthetic source-revision journey with cleanup.
- Approval gate: fresh exact release version/SHA, migration and production
  authority are required after SA-05 identifies the immutable candidate.
- Blocker / next action: owner authorization for that exact packet.
- Cleanup / rollback: packet-bound rollback plus disposable synthetic cleanup.

## Decisions and approvals

| ID | Decision or exact approved mutation | Evidence | Owner | State |
|---|---|---|---|---|
| SA-D01 | Implement stage 4 locally and use Graphify plus bounded cheap agents | `OWNER-CONFIRMED` 2026-09-28 "делай" | Kamilya owner | USED |
| SA-D02 | AI creates drafts; publication and retraining remain explicit methodologist actions | Product invariant and accepted plan | Kamilya owner | OPEN |
| SA-D03 | Do not touch customer tenants or provider billing/plans | Workspace/project policy | Kamilya owner | OPEN |

## Completion gate

- [x] Required local/DEV nodes satisfy their exit gates.
- [x] `BLOCKED` nodes have an accepted external condition and next owner.
- [x] No overlapping writer or unreviewed external mutation remains.
- [x] Cleanup and residual-state audit pass.
- [x] Durable facts moved to canonical documentation.
- [ ] Temporary task graph removed after transfer.
