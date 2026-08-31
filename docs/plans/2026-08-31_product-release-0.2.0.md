# Kamilya product release 0.2.0

## Scope and truth

- Owner: root orchestrator
- Repositories: `Kamilya-NEW`; `kamilya-landing`
- Environments/providers: local source, dev, GitHub CI, Vercel, VM126/CT125 production
- Last updated: 2026-08-31 Asia/Qyzylorda
- Exclusions: no tenant data, email, Ads, GTM, DNS, credentials, or unrelated product changes

| Claim area | Canonical source | Freshness / limitation |
|---|---|---|
| Product | `PROJECT.md` | Existing product contract; no boundary change |
| Current system | `docs/PROJECT-CONTEXT.md` | Runtime state requires fresh release readback |
| Production | `docs/PRODUCTION_READINESS.md` | Existing gates remain mandatory |
| Open work | `docs/PRODUCT_BACKLOG.md` | Release scope is limited to version visibility and notes |

## Ownership

| Scope or operation | Owner | Writer | Reviewer | Overlap rule |
|---|---|---|---|---|
| LMS version and cabinet UI | root orchestrator | root orchestrator | root orchestrator | no overlapping writer |
| Public updates page and footer | root orchestrator | root orchestrator | root orchestrator | no overlapping writer |
| CI, tag, dev and production release | root orchestrator | release runner after exact packet | root orchestrator | one external mutation owner at a time |

## Dependency graph

`REL-020-SOURCE -> REL-020-LOCAL-GATES -> REL-020-EXACT-SHA -> REL-020-DEV -> REL-020-PROD -> REL-020-PUBLIC-READBACK`

## Nodes

### REL-020-SOURCE — Versioned product and release-notes UI

- Status: `IN_PROGRESS`
- Scope: both repositories, exact files named in the owned change set
- Owner: root orchestrator
- Writer: root orchestrator
- Write/mutation scope: manifests, changelog, release note, profile version card, localized landing updates page and footer
- Dependencies: none
- Exit gate: source reflects `0.2.0` consistently and both locales have natural user-facing copy
- Evidence: `GIT-DERIVED`: pending diff review; `RUNTIME-DERIVED`: NOT VERIFIED
- Approval gate: owner instruction `делай` for the proposed `0.2.0` release package
- Blocker / next action: complete source patch, then request validation gate
- Cleanup / rollback: revert only the owned release hunks before external release

### REL-020-LOCAL-GATES — Deterministic validation

- Status: `NOT_STARTED`
- Scope: both repositories
- Owner: root orchestrator
- Writer: none
- Dependencies: `REL-020-SOURCE`
- Exit gate: version validator, focused UI tests, localization checks, typecheck, tests and production builds pass sequentially
- Evidence: `GIT-DERIVED`: NOT VERIFIED
- Approval gate: explicit permission required before running validation under the current collaboration contract
- Blocker / next action: owner validation permission
- Cleanup / rollback: NOT APPLICABLE

### REL-020-EXACT-SHA — Immutable release commit and tag

- Status: `NOT_STARTED`
- Scope: GitHub repositories
- Owner: root orchestrator
- Writer: release runner only after a complete exact packet
- Dependencies: `REL-020-LOCAL-GATES`
- Exit gate: exact clean release commits, green CI, tag `v0.2.0`, independent remote readback
- Evidence: `PROVIDER-CONFIRMED`: NOT VERIFIED
- Approval gate: exact push/tag packet after local gates
- Blocker / next action: local gates and exact SHA do not yet exist
- Cleanup / rollback: do not move or reuse the version tag

### REL-020-DEV — Dev acceptance

- Status: `NOT_STARTED`
- Scope: approved dev contour
- Owner: root orchestrator
- Writer: release runner after exact packet
- Dependencies: `REL-020-EXACT-SHA`
- Exit gate: cabinet version card, RU/KK updates pages, footer links, and navigation read back on exact SHA
- Evidence: `RUNTIME-DERIVED`: NOT VERIFIED
- Approval gate: exact dev deployment packet
- Blocker / next action: exact SHA required
- Cleanup / rollback: redeploy prior accepted dev SHA

### REL-020-PROD — Production release

- Status: `NOT_STARTED`
- Scope: Kamilya production application and public landing
- Owner: root orchestrator
- Writer: release runner after exact packet
- Dependencies: `REL-020-DEV`
- Exit gate: exact version, image, migration, worker, Vercel, and public UI readback
- Evidence: `RUNTIME-DERIVED`: NOT VERIFIED; `PROVIDER-CONFIRMED`: NOT VERIFIED
- Approval gate: fresh exact production packet after dev acceptance
- Blocker / next action: dev acceptance required
- Cleanup / rollback: redeploy the exact prior accepted SHA; preserve additive migrations

### REL-020-PUBLIC-READBACK — User-visible release proof

- Status: `NOT_STARTED`
- Scope: production cabinet and `www.kml.kz`
- Owner: root orchestrator
- Writer: none
- Dependencies: `REL-020-PROD`
- Exit gate: normal user sees `Kamilya LMS 0.2.0`; RU and KK footer links open matching release notes; no raw SHA is shown to normal users
- Evidence: `RUNTIME-DERIVED`: NOT VERIFIED
- Approval gate: read-only after production release
- Blocker / next action: production release required
- Cleanup / rollback: NOT APPLICABLE

## Decisions and approvals

| ID | Decision or exact approved mutation | Evidence | Owner | State |
|---|---|---|---|---|
| DEC-020-01 | Use `0.2.0` for the current backwards-compatible feature release | `OWNER-CONFIRMED`: user accepted proposed implementation | owner | USED |
| DEC-020-02 | Show human product version in profile and landing footer; keep SHA operational | `OWNER-CONFIRMED`: user requested cabinet/landing visibility | owner | USED |

## Completion gate

- [ ] Required nodes satisfy their exit gates.
- [ ] No overlapping writer or unreviewed external mutation remains.
- [ ] Cleanup and residual-state audit pass.
- [ ] Durable facts moved to canonical documentation.
- [ ] Temporary task graph removed after transfer.

## Scope extension — trial usability and finance content eligibility

`REL-020-SOURCE -> REL-020-TRIAL-CONTRACT -> REL-020-LOCAL-GATES`

`REL-020-SOURCE -> REL-020-FINANCE-ELIGIBILITY -> REL-020-LOCAL-GATES`

### REL-020-TRIAL-CONTRACT — Verified trial reaches first value

- Status: `IN_PROGRESS`
- Scope: tenant registration, assigned roles, first-session route, and trial limits
- Owner: root orchestrator
- Writer: root orchestrator
- Write/mutation scope: registration role assignment, response token, copy, and integration regression
- Dependencies: `REL-020-SOURCE`
- Exit gate: verified registration returns active `methodologist` plus assigned `admin`; the same token lists permitted blueprints and creates the first course within trial limits
- Evidence: `GIT-DERIVED`: source and integration regression prepared; `RUNTIME-DERIVED`: NOT VERIFIED
- Approval gate: owner instruction to verify real trial interface usability
- Blocker / next action: local DB-backed gate, then bounded dev browser trial
- Cleanup / rollback: disposable trial fixture must be removed after dev acceptance

### REL-020-FINANCE-ELIGIBILITY — Finance-only blueprint is tenant-bound

- Status: `IN_PROGRESS`
- Scope: tenant schema, superadmin edit UI, blueprint list/read/instantiate APIs
- Owner: root orchestrator
- Writer: root orchestrator
- Write/mutation scope: additive migration `0139`, tenant schemas, superadmin field, server-side blueprint eligibility, focused tests
- Dependencies: `REL-020-SOURCE`
- Exit gate: false/default tenants cannot list, read, or instantiate the finance blueprint; true tenants retain the complete flow
- Evidence: `GIT-DERIVED`: source and integration regressions prepared; `RUNTIME-DERIVED`: NOT VERIFIED
- Approval gate: owner instruction to add the financial-organization property and hide the finance pre-course when false
- Blocker / next action: local migrated PostgreSQL gate and dev UI readback
- Cleanup / rollback: application rollback may leave the additive false-default column in place
