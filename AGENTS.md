# AGENTS.md — Инструкции для AI-агента

> Этот файл — entry point для AI-агента средней мощности (Qwen 3.5 / DeepSeek V3 / Claude Sonnet 4),
> который будет реализовывать LMS.

## Что строим

**Kamilya LMS Core v1.0** — полноценный LMS-модуль, заменяющий Chamilo 2.0.
Не форк, не обёртка. Собственный продукт.

**Главный документ:** [`TZ.md`](./TZ.md) — читай ПЕРВЫМ, в нём 18 разделов с деталями.

**Архитектурные решения:** [`docs/adr/`](./docs/adr/) — 3 ADR уже есть, новые решения добавляй туда.

## Что ты получишь на входе

- **Qwen LLM (3.5)** — для генерации курсового контента
- **PostgreSQL 16** (уже работает у Kamilya)
- **Existing Kamilya API** — `/api/v1/courses`, `/api/v1/identity/users` и т.д. (см. `apps/api/../` — портируй)
- **JWT auth** (уже реализован в Kamilya)
- **Tenant context** (JWT содержит `tenant_id`)

## Что нужно сделать (12 недель)

Полный план в [`TZ.md § 15`](./TZ.md#15-этапы-разработки-12-недель).

**Краткая сводка по неделям:**
1. **W1-2:** Foundation (монорепо, Docker, CI/CD, auth, дизайн-система)
2. **W3-4:** Course CRUD + structure editor
3. **W5-6:** AI generation pipeline
4. **W7-8:** Student UX + Quizzes + Certs
5. **W9-10:** Analytics + Admin + Audit
6. **W11:** Performance + Security + i18n
7. **W12:** Beta launch

## Архитектурные правила (соблюдай строго)

### 1. Type safety end-to-end
- Backend: Pydantic v2 schemas
- Frontend: Zod schemas
- Codegen: Pydantic → Zod через `packages/shared-types/codegen.py`

### 2. Multi-tenancy (КРИТИЧНО)
- **Каждый** query фильтрует по `tenant_id`
- Прямой SQL запрещён — только через ORM/repositories
- RLS enforced в Postgres (см. ADR-0003)
- Любой PR без tenant filter = **rejected**

### 3. Backend: модульная монолитная архитектура
```
backend/app/modules/<feature>/
├── models.py        # SQLAlchemy
├── schemas.py       # Pydantic
├── service.py       # Бизнес-логика
├── repository.py    # DB queries
├── router.py        # FastAPI endpoints
└── tests/
```
Зависимости между модулями — только через DI. Прямой импорт — на code review.

### 4. Frontend: feature-based
```
apps/web/src/features/<feature>/
├── components/
├── hooks/
├── api.ts            # API client (через TanStack Query)
├── types.ts          # Zod-inferred types
└── pages/            # Next.js routes (если нужно)
```

### 5. Performance budget
- API P95 ≤ 800ms
- Page P95 ≤ 2.5s
- Не оптимизируй преждевременно — measure first

### 6. Security
- Pydantic validation на каждом endpoint
- File upload: MIME check (magic bytes, не расширение)
- Rate limiting (Redis-based)
- Все passwords хешируются через `argon2` (не bcrypt)
- Никогда не логируй JWT, password, или PII

### 7. Testing
- Unit: ≥ 80% coverage для service.py и repository.py
- Integration: каждый endpoint
- E2E (Playwright): critical paths (login, create course, take quiz)

## Что ты получишь от меня (human architect)

- Ответы на вопросы по `TZ.md` если что-то неясно
- Code review на каждый PR
- Финальный QA перед GA

## Что ты НЕ должен делать

- ❌ Создавать микросервисы (v1.0 = монолит)
- ❌ Использовать SCORM (это v1.1)
- ❌ Делать mobile native apps (это v2.0)
- ❌ Писать custom WYSIWYG (используй Tiptap)
- ❌ Использовать polling вместо WebSocket для real-time
- ❌ Добавлять features не из TZ без обсуждения

## Workflow для агента

### Начало работы (День 1)

1. Прочитай `TZ.md` целиком (~1 час)
2. Прочитай все 3 ADR (~20 минут)
3. Сделай `git clone` и настрой окружение
4. Создай `apps/web/`, `apps/api/`, `packages/db-schema/` со skeleton
5. Начни с Недели 1 задач: docker-compose, DB migrations (tenants, users)

### Каждый день

1. **Перед кодом:** уточни требования в TZ
2. **Code:** следуй архитектурным правилам выше
3. **Tests:** пиши тесты параллельно с кодом (TDD опционально, но unit tests обязательны)
4. **Self-review:** перед commit, проверь:
   - Все queries имеют `tenant_id` filter?
   - Все endpoints имеют Pydantic schemas?
   - Все строки i18n-ized (RU)?
   - Нет хардкода хостов, секретов?
5. **Commit:** atomic, conventional commits
6. **PR:** ссылка на issue/ADR, описание изменений

### Перед merge (Definition of Done)

См. [`TZ.md § 16`](./TZ.md#16-definition-of-done).

## Полезные команды

```bash
# Setup
pnpm install                                    # frontend deps
python -m venv .venv && source .venv/bin/activate
pip install -e packages/db-schema
pip install -e apps/api

# Dev
docker compose up postgres redis minio           # инфра
pnpm dev                                          # Next.js
uvicorn apps.api.main:app --reload --port 8000   # FastAPI
celery -A apps.api.workers worker -l info        # Celery

# Test
pytest -xvs                                       # backend
pnpm test                                         # frontend
pnpm e2e                                          # Playwright

# DB
alembic upgrade head                              # миграции
alembic revision --autogenerate -m "..."          # новая миграция
psql postgresql://...                             # ручные запросы

# Deploy
docker build -t lms-api apps/api
docker push ...
ssh root@vps.kamilya.kz 'cd /opt/lms && git pull && docker compose up -d'
```

## Структура репозитория (для быстрого orientation)

```
lms/
├── TZ.md                          # ← ГЛАВНЫЙ ДОКУМЕНТ
├── README.md
├── AGENTS.md                      # ← ты здесь
├── apps/
│   ├── web/                       # Next.js 14
│   └── api/                       # FastAPI
├── packages/
│   ├── db-schema/                 # Drizzle + миграции
│   ├── shared-types/              # Zod ↔ Pydantic
│   ├── ui-kit/                    # Design system
│   └── ml-pipeline/               # Qwen agents
├── infra/                         # Docker, Caddy, Ansible
├── docs/
│   ├── adr/                       # ADR (уже 3)
│   ├── diagrams/                  # C4, sequence, ERD
│   └── runbooks/                  # Operations
└── .github/workflows/             # CI/CD
```

## Context7 — актуальная документация библиотек

**MCP Context7 настроен.** Используй для проверки актуальных API и версий библиотек перед использованием.

### Когда использовать Context7
- Перед использованием API любой библиотеки (Next.js, FastAPI, SQLAlchemy, Tailwind, etc.)
- При ошибке «module not found» или «function doesn't exist» — проверь актуальную сигнатуру
- При выборе между deprecated и новым API
- Когда нужен конкретный пример использования с правильными импортами

### Примеры использования
```
use context7 to show me how to use FastAPI dependency injection
use context7 for Next.js 14 App Router dynamic params
use context7 for SQLAlchemy 2.0 async session patterns
use context7 for Tailwind CSS 3.4 container queries
use context7 with /vercel/next.js for middleware patterns
```

### Модули проекта (проверяй актуальность через Context7)
| Модуль | Библиотека | Context7 query |
|--------|-----------|----------------|
| Backend API | FastAPI | `use context7 for FastAPI middleware CORS` |
| ORM | SQLAlchemy 2.0 | `use context7 for SQLAlchemy 2.0 async select` |
| Migrations | Alembic | `use context7 for Alembic autogenerate` |
| Queue | Celery | `use context7 for Celery task retry` |
| Frontend | Next.js 14 | `use context7 with /vercel/next.js for App Router` |
| Styling | Tailwind | `use context7 for Tailwind custom colors` |
| State | Zustand | `use context7 for Zustand persist middleware` |
| Forms | React Hook Form | `use context7 for react-hook-form validation` |
| Charts | Recharts | `use context7 for Recharts responsive container` |

---

## Промпт-инструменты (для AI agent)

### Если нужна помощь по конкретной feature

```
Use this template:

"Реализуй [FEATURE_ID] из TZ.md § 3. Требования:
- Tenant isolation обязательна
- Pydantic schemas для всех endpoints
- i18n строки (RU primary)
- Unit tests ≥ 80% coverage
- Backend: модуль в apps/api/app/modules/[feature]/
- Frontend: feature в apps/web/src/features/[feature]/

Контекст: [paste relevant TZ section]
Зависимости: [list of related modules]
```

### Если застрял

```
"I'm stuck on [PROBLEM]. I tried [WHAT_YOU_TRIED].
Expected: [EXPECTED_BEHAVIOR]
Actual: [ACTUAL_BEHAVIOR]
Relevant TZ sections: [sections]
Relevant ADR: [adr paths]
What I need: [specific question]"
```

## Метрики успеха (для v1.0 GA)

- Time to first course: ≤ 30 мин
- AI generation cost: ≤ 0.10 USD
- P95 page load: ≤ 2.5s
- Uptime: ≥ 99.5%
- Languages: RU (100%), KK (80%), EN (90%)
- WCAG AA: 100% ключевых экранов

## Контакт

Если что-то неясно в TZ или нужен architectural review:
- Создай issue в GitHub с тегом `question`
- Упомяни конкретный раздел TZ

---

**Готов начать? Открой [`TZ.md`](./TZ.md) и начни с раздела 15 (этапы разработки).**

---

## Domain context (актуально на 2026-06-25)

Факты о кодбазе, которые нужны ЛЮБОМУ агенту перед началом работы — обнаружены при реализации employee-onboarding epic. Если что-то изменилось — обнови.

### Нет email-сервиса
В проекте **нет** SMTP, SendGrid, Mailgun, SES и любых других провайдеров email-рассылки. Это осознанное решение для v1.0:
- Все приглашения пользователям идут через **copy-paste invite URL** (методолог копирует → шлёт в Slack/Telegram/почту вручную)
- Для фич, где требуется автоматическое уведомление по email (например, certificate email, deadline reminder) — это **отдельный epic** с интеграцией провайдера + шаблоны + DKIM/SPF
- Если твоя фича требует "отправить email" — это блокер для v1, обсуди с Askar'ом

### tenant_settings — конфиг тенанта
Таблица `tenant_settings` (1-to-1 с tenants) хранит per-tenant настройки:
```
id, tenant_id, logo_url, primary_color, default_language ('ru'|'kk'|'en'),
self_enrollment ('true'|'false'), quiz_pass_threshold (str, default "80"),
invite_expiry_days (int, default 3, range 1-30)  -- added 2026-06-25
```
Когда нужна per-tenant настройка (язык, лимиты, флаги) — добавляй колонку сюда с разумным default. Не плоди новые таблицы.

### Public frontend URL — конфиг
`PUBLIC_URL` (apps/api/app/core/config.py, default `https://app.kml.kz`) — используется для построения invite-ссылок и любых внешних URL, которые видит пользователь. Если backend деплоится отдельно от frontend — укажи frontend URL здесь.

### Alembic migrations
- Команда: `cd apps/api && alembic upgrade head` (env.py использует async pattern)
- Pre-existing баг (исправлен в master, commit `9734c8e`): env.py был сломан (sync `with` на `AsyncConnection`), 9 миграций имели битые `down_revision` refs. **Сейчас работает** — но если добавляешь новую миграцию, используй формат `down_revision = "0001"` (short rev_id, не filename)
- В `Dockerfile` уже стоит `alembic upgrade head && uvicorn ...` — миграции применяются автоматически на каждом deploy

### Multi-tenancy (КРИТИЧНО)
- **Каждый** query фильтрует по `tenant_id`
- Прямой SQL запрещён — только через ORM/repositories
- Любой PR без tenant filter = **rejected**
