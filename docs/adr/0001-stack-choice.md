# ADR-0001: Технологический стек Kamilya LMS Core

**Дата:** 2026-06-21 · **Статус:** Accepted · **Автор:** Kamilya Tech

## Контекст

Kamilya LMS Core заменяет Chamilo 2.0 как LMS-модуль платформы.
Нужно выбрать стек для frontend и backend. Ограничения:

- Backend Kamilya уже на Python/FastAPI (нельзя выбирать другое)
- Бюджет — VPS (Hetzner/Contabo), не AWS
- Qwen LLM (3.5/Embedding-8B) уже работает в Kamilya
- Multi-tenant SaaS

## Решение

### Frontend
- **Next.js 14 (App Router)** + **TypeScript strict**
- **Tailwind CSS 3.4** + **Radix UI** (primitives)
- **TanStack Query** (server state) + **Zustand** (client state)
- **Tiptap 2** (rich text editor) + **react-hook-form + Zod** (forms)
- **next-intl** (i18n)
- **Mux Player / Video.js** (видео)
- **Vitest** + **Playwright** (testing)

### Backend
- **Python 3.12** + **FastAPI 0.110+**
- **SQLAlchemy 2.0 (async)** + **Alembic** (миграции)
- **Pydantic v2** (валидация)
- **Celery + Redis** (task queue)
- **PyJWT** (auth)
- **pytest + pytest-asyncio** (testing)

### Database
- **PostgreSQL 16** + **pgvector** (single source of truth)
- Row-Level Security для tenant isolation

### AI/ML
- **Qwen 3.5** через WireGuard (уже работает)
- **Qwen3-Embedding-8B** (уже работает)
- НЕ Qdrant, НЕ OpenAI (только как fallback)

### Infrastructure
- **Docker + Docker Compose** (v1.0; K8s в v2.0)
- **Caddy 2** reverse proxy (auto-TLS, simple)
- **GitHub Actions** (CI/CD)
- **Prometheus + Grafana + Loki** (observability)
- **Sentry** (errors)
- **Restic + B2** (backups)

## Обоснование

| Альтернатива | Почему отвергли |
|--------------|-----------------|
| React + Vite (не Next.js) | Нет SSR — хуже SEO, медленнее first paint |
| NestJS / Express (не FastAPI) | Не интегрируется с Kamilya backend, Python AI ecosystem |
| GraphQL | Overhead для простых CRUD; FastAPI + OpenAPI быстрее для типизированных клиентов |
| Drizzle vs Prisma | Drizzle: zero-cost, SQL-first, лучше для performance. Prisma: тяжелый runtime, query engine |
| Remix | Меньше экосистемы, чем Next.js |
| Postgres + Elasticsearch | Два хранилища = две проблемы. Postgres FTS + pgvector достаточно |
| Mux / Cloudflare Stream | Зависимость от вендора, $$$, достаточно FFmpeg |

## Последствия

### Положительные
- TypeScript end-to-end (минимум context switching)
- Один язык запросов (PostgreSQL) → проще эксплуатация
- Готовые компоненты (Radix, Tiptap) → быстрая разработка
- VPS-friendly, не нужен Kubernetes
- Qwen уже работает → экономия 3-4 недель на AI setup

### Отрицательные
- Видео transcoding самописный (FFmpeg) — нет готового pipeline как в Mux
- pgvector менее зрелый, чем Qdrant (но для 5K embeddings ОК)
- S3 не managed — своя забота о backup/replication
- Нет managed Kubernetes — ручной deploy

## Ревью

- [ ] Chamilo replacement specs
- [ ] Kamilya existing stack compatibility
- [ ] Budget constraints (VPS)
- [ ] Team capabilities (TypeScript, Python)

**Принято:** 2026-06-21
