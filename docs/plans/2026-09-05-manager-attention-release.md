# Manager attention R1/R2 release task graph

Owner/root: Astra. Product owner: workspace owner.
Owner instruction 2026-09-05: finish tests using the three open owner mailboxes,
then deploy this work to production. No billing/provider-plan, unrelated feature,
mailbox settings, security weakening, controller upgrade or customer-data changes.
Kamilya-NEW starting HEAD 3ff64db8f221f5fe532b16000fe62a70f89ee6a5;
remote master/dev aaebce32580586f6109d80c6dd5aad542691348b (fresh readback).
Dirty work includes unrelated docs/skills/marketing; never stage it wholesale.

## Ownership and dependency graph

Root owns DB, providers, recipient handling, integration, Git and release.
Luna/medium is read-only release-scope reviewer; no mailbox or secret access.
`PREFLIGHT -> EXACT-CI/build-only -> PILOT -> PROD-ROLLOUT -> READBACK`

Build-only may precede the mailbox pilot so the pilot can use the exact candidate
with the existing production SMTP transport without switching customer traffic.
DEV root configuration uses Resend; it is not evidence for production SMTP.

| Node | Status | Exit gate | Authority/cleanup |
|---|---|---|---|
| PREFLIGHT | IN_PROGRESS | exact scope, provider/runtime/DB/previous-image identity | read-only; no shared changes |
| PILOT | NOT_STARTED | <=1 intended reminder per each of 3 confirmed owner inboxes, visible mail and safe links, no duplicate | current owner pilot request; disposable isolated DEV fixture cleanup |
| EXACT-CI | NOT_STARTED | exact reviewed commit, canonical-account push/readback, complete CI including migrated DB/tenant contracts | owner production request; preserve unrelated dirty work |
| PROD-ROLLOUT | NOT_STARTED | protected release plane, exact 0151->0152 additive migration, fresh verified backup, API+workers+Vercel exact identity | bind exact candidate/rollback before mutation; no blind provider switch |
| READBACK | NOT_STARTED | independent DB, four services, timer, frontend and synthetic user flow | cleanup only test-owned objects; preserve inbox evidence |

## Current bounded evidence

- SMTP V2 addendum implemented; 49 transport/worker tests PASS. Stable SMTP
  Message-ID proves acceptance only; SQL suppresses all automatic SMTP retries.
- Supabase DEV SQL contracts: 21 PASS including SMTP crash and transport-change
  suppression; shared-public writes=0, provider calls=0, remaining schemas=0.
- Supabase schema-only assembled application: 8 PASS (HTTP -> materializer ->
  memory Celery -> real store/renderer), provider calls=0, remaining schemas=0.
- Python baseline unchanged: ruff=1091, mypy=2356; frontend tsc PASS.
- Full unit rerun: 1025 PASS. First run: 1024 PASS and an unrelated intermittent
  assistant policy test failed. Read-only diagnosis reproduced a UUID being
  misclassified as a phone number. This is an open separate issue, not a fix
  included in this release and not evidence that every run is stable.
- Four new native DB integration tests added for ordinary CI. Actual full
  historical migration execution remains pending; collect-only is not DB proof.
- Browser confirmed existing persistent synthetic tenant
  `83552ce6-8058-4561-abe3-cfbda14e030a`. No customer tenant is a pilot target.
  Exiting impersonation ended the browser session; owner sign-in requested.

Existing sources: AGENTS, PROJECT-CONTEXT, infra/deploy/README.md (stable
release plane), PRODUCTION_READINESS, ERRORS; skill's historical per-release
manual-build narrative is not the current routine release route. Proposed skill
alignment requires owner approval; do not edit it during this release.
