# Evidence course engine V2 release

## Scope and truth

- Owner: root Codex; product owner and release authority: workspace owner.
- Repository: `KamillaLMSCRM/Kamilya-NEW`, baseline `e00729d1cfc1c488ea54194a41f073e138dc3b2a`.
- Environments: local isolated worktree, Supabase DEV/test, Render DEV, Vercel production frontend only if changed, KZ production VM126/CT125.
- Last updated: 2026-09-15 Asia/Qyzylorda.
- Exclusions: no billing/plan changes, no DNS/proxy changes, no customer-record smoke, no automatic course publication, no schema migration unless separately added and approved.

| Claim area | Canonical source | Limitation |
|---|---|---|
| Product | `PROJECT.md` | Source behavior; runtime requires readback |
| Current system | `docs/PROJECT-CONTEXT.md` | Topology, not live status |
| Production | `docs/PRODUCTION_READINESS.md` | Historical evidence must be refreshed |
| Journey | `docs/critical-journeys/ai-course-generation.json` | Exact required tests and smokes |

## Ownership

| Scope or operation | Owner | Writer | Reviewer | Overlap rule |
|---|---|---|---|---|
| V2 engine and application adapter | root | root | independent reviewer | one writer |
| Integration map | root | none | read-only worker | no edits |
| Test evidence | root | Test & Evidence Runner ledger only | root | runner cannot repair |
| Git/release/deploy | root | Release Runner for exact packet | root | exact SHA only |

## Dependency graph

`V2-DESIGN -> V2-INTEGRATE -> V2-LOCAL-GATE -> V2-DEV -> V2-RELEASE -> V2-PROD-SMOKE`

## Nodes

### V2-DESIGN — Accepted module contracts

- Status: `DONE`
- Scope: `docs/product/evidence-course-engine-v2/`
- Exit gate: public seam, invariants, impact and tests are explicit.
- Evidence: `OWNER-CONFIRMED` current instruction; `GIT-DERIVED` contract files.
- Approval gate: current owner instruction authorizes implementation and production rollout after gates.

### V2-INTEGRATE — Production-shaped direct-source generation

- Status: `DONE`
- Scope: `apps/api/app/modules/ai/evidence_engine/**`, public pipeline adapter, focused tests.
- Exit gate: direct-source job returns a publishable mapped course or a controlled retryable failure; no partial persistence.
- Evidence: 118 focused provider/persistence/cancellation tests PASS; production-
  shaped Excel and PDF simulations are publishable with zero deterministic
  fallbacks; exact diagnostics are stored under `.release-evidence/`.
- Cleanup / rollback: no migration; revert exact release image if production acceptance fails.

### V2-LOCAL-GATE — Exact candidate verification

- Status: `DONE`
- Dependencies: `V2-INTEGRATE`.
- Exit gate: focused/module/contract tests, `AI-COURSE-01`, quality, type/static checks and graph comparison pass.
- Evidence: backend unit `1736 passed`; frontend `113 files / 594 tests`,
  typecheck, lint and 63-route production build PASS; local critical-journey
  profile READY with 7 pytest cases; changed-code Ruff check PASS after excluding
  documented legacy whole-file findings.

### V2-DEV — Isolated provider-backed acceptance

- Status: `DONE`
- Dependencies: `V2-LOCAL-GATE`.
- Exit gate: exact DEV SHA, provider route, one synthetic Excel-shaped and one narrative source flow, cleanup.
- Approval gate: existing DEV resources only; no paid resource or plan change.
- Evidence: `HBR-DEV-APP-20260915T033815Z` READY on PostgreSQL 17 + pgvector;
  RLS/FORCE RLS, activation/rollback and cleanup passed, disposable schema was
  removed and public revision `0158` remained unchanged.

### V2-RELEASE — Exact no-migration production rollout

- Status: `IN_PROGRESS`
- Dependencies: `V2-DEV`.
- Exit gate: CI and immutable image identity, backup/rollback readiness, synchronized API and three workers, frontend compatibility.
- Approval gate: `OWNER-CONFIRMED` 2026-09-15 production rollout after successful gates.

### V2-PROD-SMOKE — Bounded user-visible acceptance

- Status: `NOT_STARTED`
- Dependencies: `V2-RELEASE`.
- Exit gate: synthetic upload/index/generate/readback verifies modules, lessons, quizzes, source grounding and cleanup with zero invitations.

## Decisions and approvals

| ID | Decision or exact approved mutation | Evidence | Owner | State |
|---|---|---|---|---|
| DEC-V2-001 | Replace direct-source generation internals with V2 after local/DEV acceptance; preserve draft review/publication workflow | `OWNER-CONFIRMED` 2026-09-15; local and DEV gates PASS | Product owner | ACCEPTED |
| DEC-V2-002 | Deploy exact accepted candidate to KZ production with no migration and existing provider/resources | `OWNER-CONFIRMED` 2026-09-15 | Product owner | OPEN |
| DEC-V2-003 | Use `voyage-4-lite -> voyage-4 -> voyage-4-large -> three Qwen replicas -> Cohere`; batch course queries and never compare unrelated embedding spaces. After owner added billing, the production-shaped PDF probe returned HTTP 200 and the full 1,076-chunk Excel embedded through lite in 7.725 seconds. | Live API/Excel/PDF evidence 2026-09-15 | Product owner | ACCEPTED |

## Completion gate

- [ ] Required nodes satisfy their exit gates.
- [ ] No overlapping writer or unreviewed external mutation remains.
- [ ] Cleanup and residual-state audit pass.
- [ ] Durable facts move to canonical documentation.
- [ ] Temporary task graph is removed after transfer.
