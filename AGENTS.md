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
