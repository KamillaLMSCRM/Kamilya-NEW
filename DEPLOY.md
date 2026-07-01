# Kamilya LMS Production Deployment

Актуально на 2026-07-01.

## Production Topology

| Component | Runtime |
|---|---|
| Web | Vercel, `https://app.kml.kz` |
| API | Render, service `kamilya-lms-api`, id `srv-d8rp8ej7uimc73fglid0` |
| DB | Supabase Postgres, pooler `aws-1-eu-central-1.pooler.supabase.com` |
| Storage | Supabase Storage, bucket `Kamilya LMS` |
| Redis | Upstash Redis |
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
```

Rules:

- `DATABASE_URL` is runtime only and must use `lms_app`.
- `MIGRATION_DATABASE_URL` is for Alembic and may use admin DB role.
- Supabase service role key stays backend-only.
- Frontend must never receive service role secrets.

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

Current production state after 2026-07-01 cutover:

```text
0040 (head)
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

Deployment/update:

```bash
cd /opt/kamilya-worker
git pull origin master
systemctl restart kamilya-worker
systemctl is-active kamilya-worker
```

The worker env is `/opt/kamilya-worker/apps/api/.env`. It must use the same `DATABASE_URL` / `MIGRATION_DATABASE_URL` split as Render.

## Rollback

Render:

1. Open Render service `kamilya-lms-api`.
2. Roll back to the previous successful deploy.
3. If the issue is DB env related, restore previous env value from password manager or Render env history.

VPS worker:

1. Restore the latest `/opt/kamilya-worker/apps/api/.env.bak.*`.
2. Restart `kamilya-worker`.

Database:

- Do not downgrade production migrations unless the migration has an explicit tested downgrade path.
- Prefer forward fix migrations.
