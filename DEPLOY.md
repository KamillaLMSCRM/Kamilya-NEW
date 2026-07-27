# Kamilya LMS Production Deployment

Актуально на 2026-07-27.

Текущие release blockers ведутся в
[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

## Production Topology

| Component | Runtime |
|---|---|
| Web | Vercel, `https://app.kml.kz` |
| API | Render, service `kamilya-lms-api`, id `srv-d8rp8ej7uimc73fglid0` |
| DB | Supabase Postgres, pooler `aws-1-eu-central-1.pooler.supabase.com` |
| Storage | Supabase Storage, bucket `Kamilya LMS` |
| Queue/cache | Valkey on VPS `173.249.51.164`, TLS port `6380` |
| Worker | VPS `173.249.51.164`, systemd `kamilya-worker` |
| Docling | VPS service, `docling.kml.kz` |
| WhatsApp gateway | VPS service, `wa.kml.kz` |

The old single-VPS Docker Compose deployment is not the production architecture.

## Secrets

Do not commit secrets.

Required backend env:

```env
DATABASE_URL=postgres://lms_app.<project-ref>:<password>@aws-1-eu-central-1.pooler.supabase.com:5432/postgres
MIGRATION_DATABASE_URL=postgres://postgres.<project-ref>:<password>@aws-1-eu-central-1.pooler.supabase.com:5432/postgres
REDIS_URL=...
JWT_SECRET=...
SUPABASE_URL=...
SUPABASE_KEY=...
SUPABASE_BUCKET=Kamilya LMS
STORAGE_BACKEND=supabase
PUBLIC_URL=https://app.kml.kz
CORS_ORIGINS=["https://app.kml.kz","https://www.kml.kz"]
EMAIL_PROVIDER=resend
RESEND_API_KEY=...
EMAIL_FROM=Kamilya LMS <no-reply@notify.kml.kz>
```

Rules:

- `DATABASE_URL` is runtime only and must use `lms_app`.
- `MIGRATION_DATABASE_URL` is for Alembic and may use admin DB role.
- Supabase service role key stays backend-only.
- Frontend must never receive service role secrets.
- `RESEND_API_KEY` stays backend-only. Do not expose it in frontend env or docs.

## Backend Deploy On Render

Render service:

```text
srv-d8rp8ej7uimc73fglid0
https://kamilya-lms-api.onrender.com
```

Deploy command through Render API:

```powershell
$env:RENDER_SERVICE_ID = "srv-d8rp8ej7uimc73fglid0"
$headers = @{
  Authorization = "Bearer $env:RENDER_API_KEY"
  Accept = "application/json"
}

Invoke-RestMethod `
  -Uri "https://api.render.com/v1/services/$env:RENDER_SERVICE_ID/deploys" `
  -Method POST `
  -Headers $headers
```

Health check:

```powershell
Invoke-WebRequest `
  -Uri "https://kamilya-lms-api.onrender.com/" `
  -Method Head `
  -UseBasicParsing

Invoke-WebRequest `
  -Uri "https://kamilya-lms-api.onrender.com/api/v1/health" `
  -UseBasicParsing
```

Expected:

```json
{"status":"ok","app":"Kamilya LMS"}
```

## Database Migrations

Alembic reads `MIGRATION_DATABASE_URL` when it is set:

```powershell
cd apps/api
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini upgrade head
```

Current production state:

```text
0078 (head)
```

## Frontend Deploy On Vercel

Vercel project:

```text
web
prj_hJMzgp9QNFCwUMrsDEBZINpJJzBp
```

Required frontend env:

```env
NEXT_PUBLIC_API_URL=https://kamilya-lms-api.onrender.com/api
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

Build check:

```powershell
cd apps/web
.\node_modules\.bin\tsc.cmd --noEmit
.\node_modules\.bin\next.cmd build
```

## VPS Worker

Worker runs outside Render:

```bash
systemctl status kamilya-worker
journalctl -u kamilya-worker -f
```

Deployment/update выполняется только на выбранный release SHA:

```bash
cd /opt/kamilya-worker
git fetch origin master
git checkout --detach <release_sha>
poetry install --only main --no-interaction
poetry run python -m compileall -q app
systemctl restart kamilya-worker.service
systemctl is-active kamilya-worker.service
```

Не использовать слепой `git pull`: frontend/API docs-only commit и worker могут
иметь разные зависимости. Полная процедура, smoke и rollback описаны в
[`docs/INFRA_CELERY_WORKER.md`](docs/INFRA_CELERY_WORKER.md).

The worker env is `/opt/kamilya-worker/apps/api/.env`. It must use the same
`DATABASE_URL` / `MIGRATION_DATABASE_URL` split, `REDIS_URL`,
`SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_BUCKET` and
`STORAGE_BACKEND=supabase` as Render. Without storage parity, document
ingestion, reindex, cleanup and hash backfill run against the VPS local disk
instead of the production bucket. Valkey is exposed only through TLS with
certificate verification enabled; do not replace it with a plaintext URL.

Queue/cache checks:

```bash
systemctl status valkey-server
systemctl status valkey-certbot-renew.timer
redis-cli --tls -u "$REDIS_URL" PING
```

Valkey uses AOF persistence, `appendfsync everysec` and `maxmemory-policy noeviction`. Monitor memory, rejected writes, queue length and certificate renewal before releases that increase AI load.

## Rollback

Render:

1. Open Render service `kamilya-lms-api`.
2. Roll back to the previous successful deploy.
3. If the issue is DB env related, restore previous env value from password manager or Render env history.

VPS worker:

1. Переключить checkout на записанный предыдущий SHA.
2. Восстановить зависимости для этого SHA.
3. Restart `kamilya-worker.service`.
4. Проверить ping, registered tasks и прикладной smoke.

Database:

- Do not downgrade production migrations unless the migration has an explicit tested downgrade path.
- Prefer forward fix migrations.
