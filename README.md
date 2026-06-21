# Kamilya LMS

> AI-first корпоративная LMS для Казахстана.

## Структура

```
lms/
├── apps/
│   ├── web/          # Next.js 14 (frontend)
│   └── api/          # FastAPI (backend)
├── packages/
│   ├── db-schema/    # Drizzle ORM
│   └── ui-kit/       # UI компоненты
└── infra/            # Docker, Caddy
```

## Быстрый старт

```bash
# 1. Установить зависимости
pnpm install

# 2. Поднять инфраструктуру
docker compose up -d postgres redis minio

# 3. Миграции
cd apps/api && poetry run alembic upgrade head

# 4. Запустить dev
pnpm dev:web    # Next.js @ localhost:3000
pnpm dev:api    # FastAPI @ localhost:8000
```

## Метрики успеха

- Time to first course ≤ 30 мин
- AI cost ≤ $0.10
- P95 ≤ 2.5s
- WCAG AA 100%
