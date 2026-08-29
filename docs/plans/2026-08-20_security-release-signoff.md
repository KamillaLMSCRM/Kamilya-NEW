# Kamilya LMS — KZ security release and formal sign-off

Дата: 2026-08-20
Режим: production release + изолированные security acceptance gates.
Production load test и destructive pentest запрещены.

## Цель

Закрыть два утверждения, которые до сих пор имели статус `NO-GO`:

1. подтвердить, что локально исправленные security controls действительно
   развёрнуты и наблюдаемы в KZ production;
2. получить формальный security verdict после свежего signed restore drill,
   DB-backed PostgreSQL 17/pgvector RLS gate и production-equivalent pentest на
   disposable synthetic contour.

## Task graph

```text
SR-01 freeze release manifest and exact SHA
  -> SR-02 local regression + migration/build gates
     -> SR-03 KZ backup/snapshot + deploy + schema migration
        -> SR-04 production identity/readback + business/security smoke
           -> SR-05 signed disposable KZ restore + offsite readback
              -> SR-06 ephemeral PG17/pgvector RLS gate
                 -> SR-07 disposable three-tenant pentest
                    -> SR-08 final audit map and GO/NO-GO
```

## Stable interfaces and evidence

| ID | Interface | Required evidence | Stop condition |
|---|---|---|---|
| SR-01 | Git release manifest | explicit paths, clean index, exact commit | unrelated path or secret enters index |
| SR-02 | API/web/worker/migrations | green focused/full gates, one Alembic head | regression, multiple heads, unbuilt image |
| SR-03 | VM126 + CT125 | rollback point, exact artifact, migration owner | missing rollback or unknown live revision |
| SR-04 | `app.kml.kz` / `api.kml.kz` | deployment SHA, readiness, worker tasks, security smokes | SHA mismatch, unhealthy worker, schema drift |
| SR-05 | `kz-restore-drill.sh` | real KZ `.dump.gpg`, checksum, RPO/RTO, signed JSON, verified signature | production/non-empty target or unsigned report |
| SR-06 | `run_rls_release_gate.sh` | PG17, pgvector, role attributes, FORCE RLS, cross-tenant denial | owner/bypass role used for assertions |
| SR-07 | disposable attacker/victim/control | ROE, synthetic data, bounded tests, cleanup proof | production target, PII, tenant leakage, error spike |
| SR-08 | audit result map | per-gate PASS/FAIL/BLOCKED with timestamps | evidence missing or only source-level |

## Release manifest rule

- Never use `git add .` or deploy the dirty shared tree.
- Include only reviewed runtime, migration, deployment, test and security-runbook
  paths required by R-001..R-011.
- Preserve unrelated staff-import, marketing, legal, presentation and user work.
- If a required file mixes unrelated changes, split the patch or explicitly
  retain the gate as blocked; do not silently widen the release.

## Production safety

- Before schema/application mutation, record current SHA, Alembic revision,
  services, free disk and a usable rollback point.
- Never print `.env`, database URLs, credentials, private keys, cookies, PII or
  raw customer documents.
- Restore and pentest use disposable targets with synthetic identities. The
  production DB is never the restore target and production is not an exploit
  target.
- Any mismatch after deployment triggers rollback/hold before further gates.

## Completion state

| Gate | Status | Evidence |
|---|---|---|
| Manifest / exact SHA | DONE | `c8381617bb510909f5a97e9de244744eee31db30`; CI `32564167526` success (`GIT-DERIVED`, `PROVIDER-CONFIRMED`) |
| Local regression | DONE | API 12 passed; web 323 passed; lint, typecheck, build, Ruff, Alembic and release-contract green (`RUNTIME-DERIVED`) |
| KZ deploy/readback | DONE | API/workers exact SHA, Alembic `0122`, Vercel prod/dev `READY`, public verifier passed (`RUNTIME-DERIVED`, `PROVIDER-CONFIRMED`) |
| Signed KZ restore | DONE | signed report passed, `VALIDSIG`, offsite SHA matched, immutable archive, restore DB absent (`RUNTIME-DERIVED`) |
| DB-backed PG17 RLS | DONE | CI PG17+pgvector gate passed; live PG 17.11, pgvector 0.8.6, `lms_app`, FORCE RLS 77/77 (`RUNTIME-DERIVED`) |
| Disposable pentest | DONE | isolated CT125 DB, synthetic victim/attacker/control, 17 passed, DB/container/image/temp cleanup all zero (`RUNTIME-DERIVED`) |
| Final security verdict | GO | SR-01..SR-07 passed; bounded release and security acceptance complete (`OWNER-CONFIRMED`, `RUNTIME-DERIVED`) |

## Evidence map — 2026-08-22

- `SR-01`: release SHA `c8381617bb510909f5a97e9de244744eee31db30`
  is reachable on `origin/master` and `origin/dev`; GitHub CI run
  `32564167526` completed successfully.
- `SR-02`: focused API tests passed `12/12`; full web tests passed `323/323`;
  frontend lint and production build, backend Ruff, Alembic chain and release
  contract passed. The disposable CI PostgreSQL 17 + pgvector gate and full
  pytest/coverage job passed.
- `SR-03`: rollback image `kamilya-api:34d8b528d06` remains available. Root-only
  pre-release copies of compose and runtime env were created before replacing
  only API and three worker containers.
- `SR-04`: VM126 API and all three workers use image
  `kamilya-api:c8381617bb5`; `/health` returns `kz-production` and the exact
  release SHA. Production Vercel deployment `dpl_9gp9F3vNmN1cxnSa5JSjnWQTKv6e`
  and dev deployment `dpl_CERmDcyPPCULfTrasWdiJHyx9wX5` are `READY` on the
  same SHA. Three Celery nodes answered ping.
- `SR-05`: CT125 report
  `/var/lib/kamilya/security-evidence/kz_restore_drill_20260820T170343Z.json`
  has result `passed`; detached signature verification returned `VALIDSIG`
  fingerprint `AC17CEC046D367E1253F180787392A90B096772C`. Proxy archive SHA-256
  matched the signed report and sidecar, and the archive has immutable flag
  `i`. No disposable restore database remains.
- `SR-06`: live runtime uses PostgreSQL 17.11 and pgvector 0.8.6. Runtime role
  `lms_app` is neither superuser nor `BYPASSRLS`; all 77 RLS tables have FORCE
  RLS. Alembic is `0122`.
- `SR-07`: production-equivalent image was exercised against disposable UTF-8
  database `kamilya_pentest_20260822t0930z` with synthetic victim, attacker and
  control tenants. Cross-tenant read/write/list, anonymous and invalid-token,
  malformed-locale and compliance-isolation checks passed `17/17`. Cleanup
  evidence is zero databases, containers, derived images and temporary files.
- `SR-08`: verdict `GO`. Scheduled production smoke `32565715719` passed on
  the exact deployed SHA and automatically closed monitor issue `#3`. The
  failed pre-deploy run remains preserved as historical evidence.
