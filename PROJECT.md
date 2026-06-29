# Kamilya LMS Core v1.0

> AI-first корпоративная LMS для Казахстана. Полная замена Chamilo 2.0.
>
> **Документ актуализирован:** 2026-06-29 (после аудита 2026-06-28).
> **Статус:** Beta launch (W12 завершён).

---

## Что это

HR загружает документы (PDF/DOCX/TXT) → AI анализирует и генерирует структурированный курс → обучающиеся проходят → тесты → сертификаты. Всё в одном продукте с multi-tenancy и ролевой моделью.

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Next.js 14, Vercel Frankfurt)                    │
│  Production: https://app.kml.kz / https://www.kml.kz        │
│  Preview:    web-natt1inhm-kamillalmscrms-projects.vercel.app│
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Backend (FastAPI, Render Frankfurt)                        │
│  Service: kamilya-lms-api (srv-d8rp8ej7uimc73fglid0)        │
└────┬─────────────┬─────────────┬───────────┬───────────────┘
     │             │             │           │
     ▼             ▼             ▼           ▼
  Supabase       Upstash     Qwen LLM    Voyage / DeepSeek
  PostgreSQL     Redis       + Qwen      (failover chain,
  (pgvector)                 Embeddings  per ADR-0007)
  + Storage
  (PDF certs)
```

---

## Стек

### Backend (`apps/api`)

| Компонент | Технология |
|-----------|-----------|
| Framework | FastAPI (async) |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| Migrations | Alembic, canonical (0028+ revisions) |
| Queue | Celery + Upstash Redis |
| Auth | JWT HS256 + argon2 + 3 login flows (Telegram / public / superadmin) |
| AI (chat) | Qwen self-hosted → DeepSeek v4-flash (failover, ADR-0007) |
| AI (embeddings) | Qwen-Embedding-8B → Voyage voyage-4-lite (failover) |
| Vector store | pgvector (Supabase) |
| Object storage | Supabase Storage (PDF сертификаты) |
| Observability | Sentry + structured JSON logging |
| Rate limiting | Redis-based, fail-closed, scoped by tenant_id |
| Multi-tenancy | Row-level filters + RLS + Postgres app role (ADR-0003/0004) |

### Frontend (`apps/web`)

| Компонент | Технология |
|-----------|-----------|
| Framework | Next.js 14 (App Router) |
| Language | TypeScript strict |
| Styling | Tailwind CSS 3.4 + semantic tokens |
| State | Zustand 5 |
| HTTP | Axios |
| i18n | ru / kk / en (parity 711/711 keys) |
| A11y | WCAG 2.1 AA target (axe-core + SkipLink + Modal focus trap) |

### Инфра

| Сервис | Где |
|--------|-----|
| Database | Supabase PostgreSQL (Frankfurt), pgvector enabled |
| Redis | Upstash |
| AI LLM primary | Qwen 3.5 self-hosted (`LLM_API_URL=http://10.66.66.7:8555`) |
| AI LLM fallback | DeepSeek v4-flash (env `DEEPSEEK_API_KEY`) |
| AI Embeddings primary | Qwen-Embedding-8B (self-hosted) |
| AI Embeddings fallback | Voyage voyage-4-lite (200M free tokens) |
| Docling | `https://docling.kml.kz` (PDF/DOCX → Markdown) |

---

## Структура проекта

```
lms/
├── apps/
│   ├── api/                        ← FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py             ← entry point
│   │   │   ├── core/               ← auth, config, db, celery, security, storage
│   │   │   │   └── storage/        ← backend abstraction (local | supabase)
│   │   │   ├── models/             ← SQLAlchemy models
│   │   │   └── modules/            ← feature modules
│   │   │       ├── auth/           ← JWT + Telegram + superadmin login
│   │   │       ├── ai/             ← generation pipeline (architect/writer/assessor/reviewer)
│   │   │       ├── courses/        ← course CRUD + structure
│   │   │       ├── lessons/        ← lessons + content blocks
│   │   │       ├── quizzes/        ← quizzes + attempts + deferral
│   │   │       ├── documents/      ← file upload + RAG ingestion
│   │   │       ├── positions/      ← должности + JD analysis + staff structure
│   │   │       ├── enrollments/    ← записи на курсы
│   │   │       ├── progress/       ← прогресс обучения
│   │   │       ├── certificates/   ← сертификаты + PDF render
│   │   │       ├── users/          ← users + staff import + invitations + kiosks
│   │   │       ├── admin/          ← admin endpoints + provider-keys UI
│   │   │       ├── student/        ← student dashboard
│   │   │       ├── audit/          ← audit log read API
│   │   │       ├── integrations/   ← tenant integrations (Telegram, etc.)
│   │   │       └── demo/           ← public demo tenant routes
│   │   └── alembic/                ← 35 миграций (0001..0035)
│   │
│   └── web/                        ← Next.js 14 frontend
│       ├── src/
│       │   ├── app/                ← 16+ routes (admin, student, courses, ...)
│       │   ├── components/         ← layout + UI kit + a11y
│       │   ├── i18n/               ← ru/kk/en (711 keys, parity)
│       │   ├── lib/                ← api client, auth
│       │   └── store/              ← Zustand stores
│       └── tailwind.config.js
│
├── packages/                       ← pnpm workspaces
│   ├── db-schema/                  ← SQL reference schema (read-only)
│   ├── shared-types/               ← Zod ↔ Pydantic codegen
│   └── ui-kit/                     ← Design system tokens
│
├── infra/                          ← Docker, Caddy, monitoring
├── docs/
│   ├── adr/                        ← 10 ADRs (0001..0011, 0010 = storage backend)
│   ├── audit-2026-06-28-full.md    ← последний полный аудит
│   ├── DEPLOY.md
│   ├── DESIGN.md
│   └── WCAG.md
│
├── AGENTS.md                       ← agent instructions
├── TZ.md                           ← ТЗ (18 разделов)
├── PROGRESS.md                     ← история прогресса по неделям
├── PROJECT.md                      ← этот файл
├── render.yaml                     ← Render Blueprint
└── docker-compose.yml              ← local dev (postgres+pgvector, redis, minio)
```

---

## Функционал (на 2026-06-29)

### Реализовано

| Фича | Где |
|------|-----|
| JWT Auth + Telegram login + superadmin login | `modules/auth/` |
| Multi-tenancy (row-level + RLS + app role) | ADR-0003, ADR-0004, migration 0033 |
| Course CRUD + structure + editor | `modules/courses/`, `modules/lessons/` |
| AI generation pipeline (architect → writer → assessor → reviewer) | `modules/ai/` |
| Document upload + RAG ingestion + vector search | `modules/documents/` |
| Position management + JD analysis | `modules/positions/` |
| Auto-enroll / unenroll / deferral enforcement | `modules/positions/`, `modules/quizzes/` |
| Enrollment + progress tracking + auto-certificate issuance | `modules/enrollments/`, `modules/progress/`, `modules/courses/` |
| Quizzes + attempts + grading + deferral window | `modules/quizzes/` |
| Certificate generation (PDF via fpdf2) + Supabase Storage | `modules/certificates/` |
| Admin dashboard + user/team management | `modules/admin/`, `modules/users/` |
| Staff import (Excel/CSV) + org tree (departments/positions/employees) | `modules/users/staff_import_router.py`, `modules/positions/admin_router.py` |
| Kiosks (public token-based flow for factory floor) | `modules/users/kiosk_router.py` |
| Invitations + bulk invite (superadmin) | `modules/users/invitations_router.py` |
| Provider keys UI (encrypted Fernet) | `modules/admin/provider_keys/` |
| LLM/Embeddings failover chain | `modules/ai/llm_client.py` (ADR-0007) |
| Per-tenant LLM budget | migration 0034 |
| i18n (RU primary, KK mandatory, EN secondary) | `apps/web/src/i18n/` |
| WCAG 2.1 AA: Modal focus trap, SkipLink, axe-core tests | `apps/web/src/components/a11y/`, `apps/web/tests/a11y.test.tsx` |
| Rate limiting (Redis, tenant-scoped) | `core/rate_limit.py` |
| Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Permissions-Policy) | `core/security.py` |
| Audit log + structured logger (no PII) | `modules/audit/`, `core/` |
| Sentry + JSON logging | `core/` |
| E2E happy-path (Playwright) | `apps/web/tests/e2e/` |
| Backup scripts (restic-compatible) | `scripts/backup.sh`, `restore.sh` |
| Monitoring (Prometheus + alerts) | `monitoring/`, `docker-compose.monitoring.yml` |

### Не реализовано (по TZ)

| Фича | Когда |
|------|-------|
| SCORM support | v1.1 |
| Mobile native apps | v2.0 |
| OpenRouter / Claude в reviewer (quality tier) | отложено до отдельного epic |
| Per-tenant provider keys (сейчас только global) | нужен только UI |
| Email-сервис (SMTP/SendGrid) | блокер для v1 фич, где требуется email |

---

## Деплой

### Frontend (Vercel)

```powershell
cd D:\Камиля\lms
npx vercel deploy --prod --yes --token $env:VERCEL_TOKEN --scope $env:VERCEL_SCOPE
```

Project `web` (Vercel id `prj_hJMzgp9QNFCwUMrsDEBZINpJJzBp`), Frankfurt region.

### Backend (Render)

```powershell
$env:RENDER_API_KEY = (Get-Content apps/api/.env | Select-String 'RENDER_API_KEY' | ForEach-Object { $_.ToString().Split('=',2)[1] })
$env:RENDER_SERVICE_ID = "srv-d8rp8ej7uimc73fglid0"
Invoke-WebRequest -Uri "https://api.render.com/v1/services/$env:RENDER_SERVICE_ID/deploys" `
  -Method POST -Headers @{ Authorization = "Bearer $env:RENDER_API_KEY"; Accept = "application/json" } `
  -UseBasicParsing
```

Или через Render CLI (`render deploys create --wait`). Логи — через `render logs --resources srv-xxx --tail`.

### Git

```powershell
git add -A ; git commit -m "..." ; git push origin master
```

Render autoDeploy подхватывает push в `master`. Если не сработал — триггерим вручную через API (см. выше).

---

## Окружение

### Backend env (Render Dashboard → Service → Environment)

Ключевые: `DATABASE_URL`, `JWT_SECRET`, `REDIS_URL`, `SUPABASE_URL`, `SUPABASE_KEY`,
`SUPABASE_BUCKET`, `STORAGE_BACKEND`, `LLM_API_URL`, `DOCLING_URL`,
`DEEPSEEK_API_KEY`, `VOYAGE_API_KEY`, `PROVIDER_KEY_ENCRYPTION_KEY`,
`TELEGRAM_BOT_TOKEN`, `RENDER_API_KEY`, `SENTRY_DSN`, `CORS_ORIGINS`.

Локально — `apps/api/.env` (см. `apps/api/.env.example`).

### Frontend env (Vercel → Project → Environment Variables)

`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

Локально — `apps/web/.env.local`.

---

## Быстрые ссылки

| Ресурс | URL |
|--------|-----|
| Production | https://app.kml.kz |
| Marketing | https://www.kml.kz |
| Backend (Render) | https://kamilya-lms-api.onrender.com |
| GitHub | https://github.com/KamillaLMSCRM/Kamilya-NEW |
| Supabase | https://supabase.com/dashboard (project ref `ducegbxphkgffgozkchw`) |
| Render | https://dashboard.render.com |
| Vercel | https://vercel.com/kamillalmscrms-projects |
| Sentry | (см. `SENTRY_DSN` в env) |

---

## Где искать что

- **Контракт фичи** → `TZ.md` (§3 — функциональные требования F-001..F-018)
- **Архитектурное решение** → `docs/adr/00XX-*.md` (10 ADRs)
- **История изменений** → `git log` + `PROGRESS.md` (по неделям) + коммиты `feat(8.3)` / `fix(2.1)` etc.
- **Полный аудит** → `docs/audit-2026-06-28-full.md`
- **Структурированные уроки (Symptom→Root Cause→Fix→Detection Rule)** → `docs/LESSONS.md`
- **Деплой** → `DEPLOY.md` + `render.yaml`
- **Дизайн-система** → `DESIGN.md`
- **A11y правила** → `WCAG.md`
- **Agent instructions** → `AGENTS.md`