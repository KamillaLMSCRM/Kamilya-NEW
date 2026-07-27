# Kamilya LMS

Multi-tenant LMS для корпоративного обучения на основе документов компании.

## Текущий статус

Перед разработкой или release прочитайте:

1. [Описание продукта](PROJECT.md)
2. [Контекст проекта](docs/PROJECT-CONTEXT.md)
3. [Production readiness](docs/PRODUCTION_READINESS.md)
4. [Product backlog](docs/PRODUCT_BACKLOG.md)
5. [Правила для агентов](AGENTS.md)

Исторические отчёты и ранние ТЗ не являются источником текущего состояния.

## Структура

```text
apps/api/       FastAPI, SQLAlchemy, Alembic, Celery
apps/web/       Next.js, React, TypeScript
packages/       shared Python package
infra/          development infrastructure
docs/           current documentation
```

## Требования

- Python 3.12;
- Poetry;
- Node.js 20+ and npm;
- Docker Desktop для локального PostgreSQL/Valkey/MinIO;
- локальный `.env`, который не коммитится.

## Локальный запуск

Infrastructure:

```powershell
docker compose up -d postgres redis minio
```

Backend:

```powershell
cd apps\api
poetry install --with dev
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload --port 8000
```

Frontend:

```powershell
cd apps\web
npm install
npm run dev
```

Frontend: `http://localhost:3000`
API docs: `http://localhost:8000/docs`

## Проверки

Backend:

```powershell
cd apps\api
poetry run pytest
poetry run alembic heads
```

Frontend:

```powershell
cd apps\web
npm test
npm run typecheck
$env:NEXT_TELEMETRY_DISABLED='1'
npx next build
```

## Environment

Основные группы переменных:

- `DATABASE_URL`, `MIGRATION_DATABASE_URL`;
- `REDIS_URL`;
- `JWT_SECRET`;
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_BUCKET`;
- `RESEND_API_KEY`, `EMAIL_PROVIDER`, `EMAIL_FROM`;
- Telegram credentials;
- AI provider URLs/keys;
- frontend `NEXT_PUBLIC_*`.

Значения находятся только в локальном `.env` и provider secrets. Не печатайте
их в документацию, chat или CI output.

## Production

- Frontend: Vercel, `https://app.kml.kz`.
- API: Render, `https://kamilya-lms-api.onrender.com`.
- PostgreSQL/storage: Supabase.
- Valkey and Celery worker: VPS.

Health endpoints не доказывают готовность release. Проверяйте CI, frontend
commit, API commit, worker commit, Alembic revision и business smoke отдельно.

Deployment runbook: [DEPLOY.md](DEPLOY.md).
