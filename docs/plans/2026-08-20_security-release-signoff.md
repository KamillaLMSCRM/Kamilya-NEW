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
| Manifest / exact SHA | IN PROGRESS | — |
| Local regression | PENDING | — |
| KZ deploy/readback | PENDING | — |
| Signed KZ restore | PENDING | — |
| DB-backed PG17 RLS | PENDING | — |
| Disposable pentest | PENDING | — |
| Final security verdict | NO-GO | gates above incomplete |
