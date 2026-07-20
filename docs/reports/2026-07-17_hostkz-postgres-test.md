# HostKZ PostgreSQL test contour

**Date:** 2026-07-17
**Status:** isolated one-week test; no production cutover

## Decision boundary

- Production API and workers continue using Supabase PostgreSQL.
- Supabase was inspected read-only and was not disabled, migrated, or reconfigured.
- HostKZ contains a snapshot of test data only. It is not a production system.
- Supabase Storage and all production object URLs remain unchanged.

## Test topology

| Component | Test configuration |
|---|---|
| VPS | HostKZ, Astana, Ubuntu 24.04, 2 vCPU, 2 GiB RAM, 50 GiB NVMe |
| PostgreSQL | 16.14, bound to `127.0.0.1:5432` only |
| Vector extension | pgvector 0.6.0 |
| Connection pool | PgBouncer 1.22, transaction mode, `127.0.0.1:6432` only; 600 client connections over a 10 + 2 PostgreSQL pool |
| Runtime role | `lms_app`, login, no superuser, no `BYPASSRLS` |
| Migration role | `kml_migrator`, login, no superuser, no `CREATEROLE`, no `BYPASSRLS` |
| Test database | `kamilya_lms_test` |
| Public firewall | SSH only; PostgreSQL and PgBouncer are not public |

The server also has a 2 GiB swap file, UFW, fail2ban, key-based SSH, and
disabled password SSH authentication. At the end of setup the root filesystem
used 10%, available memory was about 1.5 GiB, and swap usage was zero.

## Access model

Secrets and local paths are stored only in the gitignored root `.env`:

- `VPS_HOSTKZ_LOGIN`, `VPS_HOSTKZ_PASSWORD`;
- `HOSTKZ_DB_RUNTIME_PASSWORD`, `HOSTKZ_DB_MIGRATION_PASSWORD`;
- `HOSTKZ_DB_RUNTIME_USER`, `HOSTKZ_DB_MIGRATION_USER`;
- `HOSTKZ_DB_DIRECT_TUNNEL_PORT`, `HOSTKZ_DB_PGBOUNCER_TUNNEL_PORT`;
- `HOSTKZ_SSH_KEY`.

Open separate local tunnels when maintenance is required:

```powershell
ssh -i $env:HOSTKZ_SSH_KEY -N `
  -L 15432:127.0.0.1:5432 `
  -L 16432:127.0.0.1:6432 `
  "$env:VPS_HOSTKZ_LOGIN@<HOSTKZ_IP>"
```

- Alembic uses direct port `15432` and the migration role.
- Runtime checks use PgBouncer port `16432` and `lms_app`.
- Do not expose `5432` or `6432` through UFW.

## Snapshot and migration result

The source Supabase snapshot was created as a PostgreSQL custom archive:

- source PostgreSQL: 17.6;
- source database size: about 24 MiB;
- public tables: 53;
- source Alembic revision: `0063`;
- archive size: about 5.7 MiB;
- SHA-256: `60e553b8fa9d2e6638e7f1602a915fdcc86e84ba13cd1c04b81c9512e5f0622a`.

The archive remains on the test VPS under the unprivileged operator account.
No row contents or secrets were printed during verification.

PostgreSQL 17 dumps include `SET transaction_timeout`, which PostgreSQL 16
does not support. The test data import therefore used `pg_restore 17` to emit a
data-only SQL stream, removed only that unsupported `SET` statement, and loaded
the stream with triggers temporarily disabled by the local system `postgres`
account. This is a migration-only operation, not an application permission.

Validation results:

- the complete Alembic chain ran from an empty database to `0065`;
- all 53 source table row counts match the HostKZ snapshot;
- every target table containing `tenant_id` has RLS enabled and forced;
- PgBouncer transaction-mode smoke test passed for two populated tenants;
- tenant context did not leak into the next transaction;
- both database roles remain non-superuser and `NOBYPASSRLS`.

The subsequent staged database load test also passed. The realistic profile
accepted 500 PgBouncer clients at 150 RLS-aware read/progress workflows per
second with zero failures, 4.108 ms sampled p95 latency and no swap use. CPU is
the first scaling limit under saturation. See
`docs/reports/2026-07-17_hostkz-load-test.md` for the method, limitations and
full results.

Reusable verification scripts:

- `scripts/compare_postgres_databases.py` compares schema and aggregate counts;
- `scripts/verify_tenant_rls.py` checks RLS and transaction-local tenant context.

## Migration-chain corrections found by the test

The clean install exposed historical assumptions about manually created
production objects. The repository now includes corrections for:

- duplicate or missing bootstrap tables and columns;
- the missing `position_courses` bootstrap table;
- long Alembic revision identifiers;
- migration-time role management that incorrectly required `CREATEROLE`;
- legacy certificate and production-schema reconciliation;
- multiple SQL commands passed to one asyncpg prepared statement;
- unsupported IVFFlat indexing for 4096-dimensional vectors;
- eight tenant-scoped tables that previously lacked RLS/FORCE RLS.

The `vector` extension and the two login roles remain infrastructure
prerequisites. Alembic validates `lms_app` instead of creating or altering a
cluster role.

## Backups

The test VPS has:

- `/usr/local/sbin/kamilya-pg-backup`;
- `kamilya-pg-backup.service`;
- `kamilya-pg-backup.timer` enabled and active;
- daily custom-format dumps in `/var/backups/kamilya-postgres`;
- SHA-256 sidecar files;
- seven-day local retention.

The first backup checksum passed, its archive TOC was readable by
`pg_restore --list`, and a full restore into a temporary database completed at
revision `0065`. The temporary restore-check database was deleted afterwards.

This is not PITR and not an off-site backup. A single VPS and a backup on the
same disk are insufficient for production.

## What this test does not prove

- The Render API and Celery worker have not been switched to HostKZ.
- Production traffic, latency, failover, PITR, monitoring, and off-site restore
  have not been tested on this server.
- Supabase Storage has not been localized.
- PostgreSQL 16 on this 2 GiB VPS is suitable for the pilot snapshot, but a
  production sizing decision requires application smoke and load tests.

## Teardown before the trial expires

1. Keep Supabase as production and verify its connection settings are unchanged.
2. Export and verify a final HostKZ dump only if the pilot results are needed.
3. Stop local SSH tunnels.
4. Destroy the test VPS in the HostKZ panel before paid renewal unless the pilot
   is explicitly extended.
5. Remove or rotate temporary HostKZ database passwords and the local SSH key.
6. Remove temporary `HOSTKZ_*` variables from the local `.env` after teardown.

Any production cutover must be a separate approved operation with a maintenance
window, fresh snapshot, delta/freeze plan, application smoke tests, rollback to
Supabase, off-site backups, and monitored acceptance criteria.
