# Kamilya LMS

> AI-first корпоративная LMS для юридических лиц Казахстана. Заменяет
> ручной онбординг через Job Descriptions автогенерируемыми курсами.
>
> **Production:** [app.kml.kz](https://app.kml.kz) ·
> **API:** api.kml.kz (Render Frankfurt) ·
> **Frontend:** Vercel (Frankfurt) ·
> **DB:** Supabase (Frankfurt) ·
> **LLM:** self-hosted Qwen on DGX + DeepSeek/Voyage failover.

## Что это

Multi-tenant SaaS для обучения сотрудников. Методолог присылает JD
(Job Description) → AI генерирует структуру курса (модули, уроки,
кейсы, тесты) → ученик проходит с проверкой знаний → получает
сертификат. Юридическая специфика: RU/KK/EN, RLS-изоляция между
компаниями, аудит-логирование.

## Quickstart (dev)

```bash
# 1. Клонировать
git clone <repo>
cd lms

# 2. Поднять инфраструктуру (postgres+pgvector, redis, minio)
docker compose up -d postgres redis minio

# 3. Установить зависимости
pnpm install                 # frontend
poetry install               # backend

# 4. Скопировать env
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local

# 5. Применить миграции
cd apps/api && poetry run alembic upgrade head && cd ../..

# 6. Запустить dev-серверы
pnpm dev                     # Next.js + FastAPI concurrently
```

UI: http://localhost:3000 · API: http://localhost:8000/docs

## Структура репозитория

```
lms/
├── apps/
│   ├── web/                       # Next.js 14 (App Router)
│   └── api/                       # FastAPI + SQLAlchemy 2.0
├── packages/
│   ├── db-schema/                 # SQL reference schema (read-only)
│   ├── shared-types/              # Zod ↔ Pydantic codegen
│   ├── ui-kit/                    # Design system
│   └── ml-pipeline/               # Qwen prompt templates
├── infra/                         # Docker, Caddy, init scripts
├── docs/
│   ├── adr/                       # 9 Architecture Decision Records
│   ├── audit-2026-06-28-full.md   # Latest full-project audit
│   └── runbooks/                  # Operations
├── scripts/ci/                    # CI and pre-commit helper scripts
├── .github/workflows/ci.yml       # CI gates (lint, test, tenant-grep, secrets)
└── AGENTS.md                      # AI agent playbook (start here)
```

## Главные документы

| Документ | Зачем |
|---|---|
| [AGENTS.md](./AGENTS.md) | Правила и архитектурные решения для AI-агентов |
| [TZ.md](./TZ.md) | Полная техническая спецификация (18 разделов) |
| [docs/audit-2026-06-28-full.md](./docs/audit-2026-06-28-full.md) | Аудит кодовой базы (36 findings, 6 critical) |
| [docs/adr/](./docs/adr/) | 9 ADR: stack, monorepo, multitenant, RLS, upload, AI, auth, storage |

## Архитектурные принципы

- **Multi-tenancy:** RLS + ORM filters + lms_app role с NOBYPASSRLS
  (audit §3.1). Cross-tenant тесты обязательны для каждого PR.
- **AI pipeline:** Qwen self-hosted (primary) → DeepSeek/Voyage
  (failover). Цена генерации курса ≤ $0.10.
- **Auth:** JWT access (15 min, in-memory) + httpOnly refresh cookie
  (30 days). XSS-устойчивое хранение.
- **Модульный монолит:** каждый feature в `app/modules/<feature>/`
  с models/schemas/service/router/tests/. Cross-module imports — на
  code review.

## Метрики успеха (v1.0 GA)

| Метрика | Цель |
|---|---|
| Time to first course | ≤ 30 мин |
| AI generation cost | ≤ $0.10 / курс |
| Page P95 | ≤ 2.5s |
| API P95 | ≤ 800ms |
| Uptime | ≥ 99.5% |
| Languages | RU 100%, KK 80%, EN 90% |
| WCAG AA | 100% ключевых экранов |

## CI/CD

Каждый PR проверяется:
- `ruff` (lint + format)
- `mypy` strict on `app/`
- `pytest --cov-fail-under=70` on `app/modules/`
- tenant-id security gate (grep)
- `detect-secrets` scan

См. `.github/workflows/ci.yml` и `.pre-commit-config.yaml`.

## Contributing

1. Прочитай [AGENTS.md](./AGENTS.md).
2. Создай feature-ветку от `main`.
3. Перед commit: `pre-commit run --all-files`.
4. PR должен проходить CI.
5. Code review от владельца архитектуры (@askar0007amirkhanov).

## Лицензия

Proprietary. © 2026 Kamilya.