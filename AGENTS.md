# AGENTS.md — Инструкции для AI-агента

> Этот файл — entry point для AI-агента средней мощности (Qwen 3.5 / DeepSeek V3 / Claude Sonnet 4),
> который будет реализовывать LMS.

## ⚠️ ОДИН АГЕНТ — контекстное окно не бесконечно (правило от 2026-06-30)

**Прежде чем просить Askar'а что-то проверить руками — СНАЧАЛА
посмотри, есть ли у тебя сам доступ.** У меня есть `apps/api/.env`
(где `DATABASE_URL` к прод-Supabase, RENDER_API_KEY, DEPLOY_KEY и
т.д.) — этого хватает чтобы самому выполнить `psql`, дёрнуть
Render API, прочитать Telegram-логи. Не перекладывай на Askar'а то,
что ты можешь сделать за 30 секунд через CLI. Потерял 30 минут
2026-06-30 на этом.

**При передаче работы другому агенту / следующей сессии** — пиши
**handoff-документ** в `docs/handoffs/<YYYY-MM-DD>_<slug>.md`:
TL;DR, что было сломано, какие коммиты, prod state, TODO, ключевые
файлы, ENV-секреты (где лежат, **не печатать значения**), project rules.
Активный план храни в `docs/plans/<slug>.md`, после завершения эпика
перенеси в `docs/plans/done/`. См. `docs/handoffs/2026-06-30_nav-fixes.md`
для примера.

В этом проекте **я один агент**. Никаких параллельных сессий, никаких
«уточни у Askar'а который залогинен где-то ещё». Если мой runtime
перезапускается между ходами — я теряю нить.

**Жёсткий workflow для ЛЮБОЙ задачи, требующей >1 шага:**

1. **Сначала пишу подробный план в `docs/plans/<YYYY-MM-DD>_<slug>.md`.**
   План = нумерованные пункты, что именно буду менять, в каких файлах,
   какие проверки. **Один план = одна задача.** Не «меню переделать»,
   а «меню: добавить X, переименовать Y, убрать Z».

2. **Выполняю пункты по одному. СРАЗУ после выполнения пункта — пишу
   отчёт под ним в том же файле плана:**
   ```markdown
   ## Пункт 1 — добавить X в Sidebar
   **Что сделал:** <файл>, <что конкретно>, <номера строк>
   **Проверки:** <tsc / grep / curl / что смотрел>
   **Статус:** ✅ done / ⚠️ partial / ❌ blocked (причина)
   ```

3. **Никогда не отчитываюсь в чате "что сделал" пока пункт НЕ
   дописан в плане.** Иначе при перезапуске сессии я не вспомню что
   было обещано vs что было сделано.

4. **Если пункт не получился — пишу честно** (`⚠️ partial` или
   `❌ blocked`) с причиной. Не «закоммитил, проверишь», если не
   проверил.

5. **В конце — итоговый коммит + ссылка на план в commit message.**

**Где живут планы:** `docs/plans/`, имена
`YYYY-MM-DD_<kebab-slug>.md`. Один файл = один эпик. Не
`plan_final_v2.md`.

**Где живут итоги выполненных эпиков:** после завершения эпика
(коммит на master, проверено в проде) — переносить план в
`docs/plans/done/YYYY-MM-DD_<slug>.md`. Не удалять.

**Зачем это:** при потере контекста следующий запуск (или текущий
после рестарта) читает `docs/plans/done/` + текущий
`docs/plans/<active>.md` и сразу понимает где мы. Без этого — каждый
рестарт = «что мы делали?».

**Антипример (как было 2026-06-30):** Askar дал ТЗ скриншотом
«сделай сайдбар по этой картинке». Я в чате сказал «готово», ничего
не дописал в файл. Следующий ход — Askar открыл прод, увидел что
ничего не работает, потратил время. **Так не делать.**## Что строим

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

---

## Mandatory skill loading (auto-applied)

**Эти skills зарегистрированы глобально** (`~/.mavis/skills/<name>/SKILL.md`) и **ОБЯЗАТЕЛЬНО** загружаются агентом перед написанием кода в соответствующем контексте. Это ECC-equivalent правил, принудительно зашитый в system prompt через AGENTS.md.

| Триггер (что делаю) | Skill (что загрузить ПЕРВЫМ) |
|---|---|
| Проектирую новый endpoint, schema, URL structure, error envelope | `skill api-design` |
| Пишу SQL/ORM query, auth code, file upload, external integration, review PR | `skill security-review` |
| Пишу service/repository код, новый тест, фикшу баг | `skill tdd-workflow` |
| Создаю router, dependency, middleware, async service, WebSocket | `skill fastapi-patterns` |
| Создаю новую таблицу, индекс, миграцию, оптимизирую запрос | `skill postgres-patterns` |
| Меняю Dockerfile или docker-compose | `skill docker-patterns` |
| Собираюсь сказать "готово/сделано/можно мержить" | `skill verification-before-completion` |

**Запрещено:**
- Писать endpoint без `api-design`
- Писать query/auth/upload без `security-review`
- Писать service/repository без `tdd-workflow`
- Писать router/middleware без `fastapi-patterns`
- Создавать миграцию без `postgres-patterns`
- Менять Docker без `docker-patterns`
- Декларировать задачу готовой без `verification-before-completion`

**Загрузить несколько skills одновременно** — нормально (например, новый endpoint с миграцией → `api-design` + `security-review` + `tdd-workflow` + `fastapi-patterns` + `postgres-patterns`).

---

## Coding standards (auto-applied)

Расширение архитектурных правил выше. Подробные паттерны — в `skill fullstack-dev`.

### Иммутабельность
- Возвращаем новые объекты, не мутируем inputs. Pydantic модели immutable by design — не переприсваивай поля.
- Исключение: ORM internal state, Alembic migration data fixups.

### Размер файлов
- 200-400 строк типично, 800 максимум. Один файл = одна ответственность.
- Если больше — split на под-модули (см. tdd-workflow § "Service is getting too big").

### Именование
- Python: `snake_case` (функции, переменные, файлы), `PascalCase` (классы)
- TypeScript: `camelCase` (переменные/функции), `PascalCase` (компоненты/типы), `kebab-case` (файлы)
- URLs: `kebab-case`, plural nouns (`/api/v1/course-modules`)
- DB: `snake_case`, plural table names (`courses`, `enrollments`)
- Enums: `Literal["draft", "published", "archived"]` в Pydantic, `VARCHAR(20) + CHECK` в DB

### Dead code & comments
- ❌ Закомментированный код в коммитах — удалять. Если временно нужен — TODO с linked issue.
- ❌ Неиспользуемые импорты/функции/ветки — удалять. ruff/pyright/tsc подскажут.
- ❌ `print()`, `console.log()`, debugger statements в production-коде.
- ✅ Комментарии объясняют "почему", не "что" (код сам себя описывает).

### Error handling
- Каждый уровень обрабатывает ошибки явно:
  - **Repository** → typed exceptions (`NotFoundError`, `ConflictError`)
  - **Service** → ловит repo exceptions, добавляет бизнес-логику, throws domain exceptions
  - **Router** → global exception handler → JSON envelope (`ErrorResponse`)
  - **UI** → `getErrorMessage(error)` маппит коды в человеко-читаемые RU/KK/EN строки
- ❌ Никогда не swallow exceptions silently (try/except: pass).
- ❌ Никогда не возвращать stack trace или internal error messages клиенту.

### Input validation
- Pydantic v2 на каждом API boundary. Fail fast at startup (validated settings), not at usage.
- Все поля с `Field(..., min_length=, max_length=)` где применимо.
- Reject unknown fields (`extra="forbid"` в BaseSchema).
- UUID4 для всех ID-полей. Enums через `Literal[...]` или `Enum`.

---

## Testing rules (auto-applied)

Расширение архитектурного правила § 7. Подробности — в `skill tdd-workflow`.

### Coverage targets
| Слой | Минимум | Гейт |
|---|---|---|
| `service.py` | 80% | CI fail-under |
| `repository.py` | 80% | CI fail-under |
| `router.py` | integration per endpoint | manual + CI |
| `schemas.py` | edge cases (max length, bad UUID) | manual |
| `pages/` Next.js | E2E critical paths | Playwright |

### Методология
- RED → GREEN → REFACTOR. Test first. Test name = behavior, не implementation.
- Unit tests mock repository layer (fast). Integration tests use real DB (transactional rollback).
- E2E (Playwright) только для critical paths: login, course creation, quiz taking, certificate generation.

### Cross-tenant test (MANDATORY для data-access endpoints)
- Tenant A создаёт ресурс → Tenant B пытается его прочитать → expect **404** (не 403).
- Тест ДОЛЖЕН быть в PR, иначе review rejection.

### Запрещено
- `assert True` без actual assertion
- Тесты с зависимостями друг от друга
- `time.sleep()` для async wait (use `await asyncio.sleep()` или polling)
- Skip тестов без linked issue

---

## Security checklist (auto-applied, before commit)

Расширение архитектурного правила § 2 + § 6. Подробности — в `skill security-review`.

### Multi-tenancy (см. § 2 выше)
- Каждый query фильтрует по `tenant_id` из JWT
- 404 для cross-tenant (не 403)
- RLS как second line of defense
- Pre-commit grep: `rg -L "tenant_id"` на всех `select(...)` queries

### Secrets & PII
- ❌ Никогда не логируй JWT, password, refresh tokens, API keys
- ❌ Никогда не коммить `.env` (только `.env.example` с dummy values)
- ❌ Никогда не хардкодь secrets в коде (`settings.X` from env)
- ✅ Pre-commit grep: `rg -i "(password|secret|api_key|jwt)\s*=\s*['\"]"`

### Auth & Authz
- JWT: `algorithms=["HS256"]` explicit (never include `"none"`)
- Required claims: `sub`, `tenant_id`, `role`, `iat`, `exp`, `aud`
- Tokens: access in memory (15min), refresh in httpOnly cookie (30 days)
- RBAC: `Depends(require_role(...))` на каждом protected endpoint.
  **Распределение ролей — по ADR-0012**: `admin`/`org_admin` владеет
  tenant-инфраструктурой, `methodologist`/`teacher` владеет контентом
  и конфигурацией штатки. **Не давай обоим доступ ко всему**: для
  каждого нового endpoint'а определи, к какому домену он относится,
  и используй минимально-нужный список ролей.

### File upload
- Magic-byte MIME check (`python-magic`), НЕ по расширению
- Filename sanitization (`re.sub(r"[^a-zA-Z0-9._-]", "_", filename)`)
- Storage key = server-generated UUID (не user-provided filename)
- Size limit enforced server-side — **10 MB default** (see ADR-0005)
- Text MIME types (`text/plain`, `text/markdown`, `text/csv`) must pass
  UTF-8 + printable-ASCII heuristic (no binary blob bypass)

### Input validation (Pydantic)
- `tenant_id`, `created_by`, `user_id` — НИКОГДА из request body/query, только из JWT
- UUID validation: `UUID4` type
- String length limits: `Field(..., min_length=3, max_length=200)`
- Enum validation: `Literal[...]` (Pydantic) + DB `CHECK` constraint

### Rate limiting
- Auth endpoints: 5/min/IP
- LLM generation: per-tenant budget (cost control)
- File upload: per-user, per-hour
- Public endpoints: per-IP, per-minute

### CORS & Headers
- `allow_origins` = explicit list (`["https://app.kml.kz", "https://www.kml.kz"]`), NEVER `"*"` в production
- Security headers (HSTS, X-Content-Type-Options, X-Frame-Options)
- HTTPS only в production

---

## Performance rules (auto-applied)

Расширение архитектурного правила § 5. Подробности — в `skill postgres-patterns`.

### Budget
- API P95 ≤ 800ms
- Page P95 ≤ 2.5s
- LCP ≤ 2.5s, FID ≤ 100ms, CLS ≤ 0.1

### Database
- ❌ Никогда N+1 queries. Используй `selectinload` / `joinedload` для eager loading.
- ✅ Indexes для всех WHERE, JOIN, ORDER BY columns. Composite: equality first, then sort.
- ✅ `EXPLAIN ANALYZE` перед оптимизацией. Без замера — нет оптимизации.
- ✅ `pool_size = (CPU × 2) + spindle_count` (start 10-20). `pool_pre_ping=True`.
- ✅ Cursor pagination для feeds/timelines (deep pages). Offset pagination для admin lists (< 10k pages).

### Async
- ❌ Никогда sync I/O в async routes (`requests`, `time.sleep`, `psycopg2` sync).
- ✅ Все I/O через async-библиотеки (`httpx.AsyncClient`, `asyncpg`, `redis.asyncio`).
- ✅ `asyncio.wait_for(..., timeout=30)` для external calls.
- ✅ Background jobs в Celery (отдельный процесс), НЕ threads в API.

### Frontend
- ✅ Server Components для default, Client Components только где нужен interactivity.
- ✅ Image optimization (`next/image`), font optimization (`next/font`).
- ✅ Code splitting (Next.js automatic per route).
- ✅ TanStack Query для server state (cache, dedupe, optimistic updates).
- ✅ Skeleton/spinner loading states, не blank screens.

### Premature optimization = ЗАПРЕЩЕНО
- Measure first (Sentry, Vercel Analytics, `EXPLAIN ANALYZE`)
- Fix the bottleneck, not the symptom
- Profile before claiming improvement

---

## Что ты получишь от меня (human architect)

- Ответы на вопросы по `TZ.md` если что-то неясно
- Code review на каждый PR
- Финальный QA перед GA

## Что ты НЕ должен делать

- ❌ Создавать микросервисы (v1.0 = монолит)
- ✅ Использовать только SCORM 1.2 в текущем scope; SCORM 2004 должен отклоняться. Полный browser/storage/production E2E всё ещё обязателен перед production claim.
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
│   ├── db-schema/                 # SQL reference schema (read-only)
│   ├── shared-types/              # Zod ↔ Pydantic
│   ├── ui-kit/                    # Design system
│   └── ml-pipeline/               # Qwen agents
├── infra/                         # Docker, Caddy, Ansible
├── docs/
│   ├── adr/                       # Architecture Decision Records
│   ├── diagrams/                  # C4, sequence, ERD
│   └── runbooks/                  # Operations
└── .github/workflows/             # CI/CD

**Note on db-schema vs Alembic:** `packages/db-schema/` holds a
SQL-only reference schema for documentation and quick eyeballing. The
**canonical migrations** live in `apps/api/alembic/versions/` and are
applied via `cd apps/api && alembic upgrade head` on startup. Never
edit `packages/db-schema/` to "fix" a migration — write a new
Alembic revision instead.
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

## Lessons learned (важно для будущих агентов)

> **Структурированные уроки (Symptom → Root Cause → Fix → Detection Rule) живут в [`docs/LESSONS.md`](./docs/LESSONS.md).** Сюда попадают только компактные доменные подсказки (формат «Урок N: …»).
>
> **Правило записи в `docs/LESSONS.md`:** если ты ловишь себя на том, что пробуешь второй fix против того же симптома (особенно после ложного «готово»), **STOP**. Прочитай `~/.mavis/agents/mavis/skills/systematic-debugging/SKILL.md` (Iron Law: NO FIXES WITHOUT ROOT CAUSE INVESTIGATION). Когда найдёшь настоящую причину — задокументируй её в `docs/LESSONS.md` в формате 4-частей. **Detection Rule** — самая важная часть: это дешёвый check, который бы поймал баг с первого раза.

### Render API access (project secret)

`RENDER_API_KEY` хранится в `apps/api/.env`. **Это проектный секрет, не персональный** — любой агент работающий с Kamilya LMS может и должен использовать его.

**Доступное через API:**
- `GET /v1/services` — список сервисов
- `GET /v1/services/{id}` — детали сервиса
- `GET /v1/services/{id}/deploys` — список деплоев (статус, commit, время)
- `GET /v1/services/{id}/events` — события deploys/builds
- `GET /v1/services/{id}/env-vars` — env vars (НЕ содержит секреты в plaintext)
- `POST /v1/services/{id}/deploys` — триггер нового деплоя (без body)

**НЕ доступно через API:**
- `GET /v1/services/{id}/logs` — возвращает 404. Runtime logs только через Dashboard UI.
- `GET /v1/services/{id}/deploys/{deployId}/logs` — тоже 404.

**Workaround для runtime logs:** добавляй `print(..., flush=True)` в production код — вывод виден в Dashboard → Logs. Либо добавь endpoint `GET /v1/admin/debug/logs` (superadmin only) который возвращает последние N строк из in-memory log buffer — тогда агент может читать логи через API.

**Типичные команды:**
```powershell
$env:RENDER_API_KEY = "rnd_xxx"  # из .env
$env:RENDER_SERVICE_ID = "srv-d8rp8ej7uimc73fglid0"  # kamilya-lms-api
$headers = @{ Authorization = "Bearer $env:RENDER_API_KEY"; Accept = "application/json" }

# Триггер деплоя
Invoke-WebRequest -Uri "https://api.render.com/v1/services/$env:RENDER_SERVICE_ID/deploys" `
  -Method POST -Headers $headers -UseBasicParsing

# Последние деплои
Invoke-RestMethod -Uri "https://api.render.com/v1/services/$env:RENDER_SERVICE_ID/deploys?limit=5" `
  -Headers $headers
```

### Ingestion & embeddings — где баги прячутся

**Урок 1: Embeddings endpoint должен быть `/embeddings`, не `/chat/completions`**
- `apps/api/app/modules/ai/llm_client.py::_BaseProviderClient._request` — общий для LLM и embeddings. До коммита `c7cd55d` хардкодил `/chat/completions`. `EmbeddingsClient` наследовал и слал embedding-запросы на chat endpoint → 4xx → цепочка падала → fallback на hash → embeddings не записывались.
- **Защита:** при изменении `_request` проверяй что endpoint overridable. В коде теперь есть `LLMProviderConfig.endpoint` с default `/chat/completions`, и `EmbeddingsClient.__init__` переопределяет на `/embeddings`. Если добавишь новый тип клиента (chat + audio + vision) — каждый должен override `endpoint`.

**Урок 2: `embedding_status` отражает chunks, не embeddings**
- `apps/api/app/modules/documents/router.py:212` ставил `success` если `chunks > 0`, где `chunks` это выход chunker (разбиение markdown), а не количество реально записанных embeddings в pgvector.
- Если `embed()` падал или все embeddings отбрасывались NaN-фильтром — статус всё равно был `success`, документ выглядел "здоровым" в UI, но `No embeddings found` при AI-генерации.
- **Защита:** статус должен основываться на `embeddings_written`, не на `chunks`. После коммита `01349f7` `ingest_file()` возвращает `embeddings_written`, router использует его.

**Урок 3: Hash embedding fallback может вернуть NaN**
- Старая реализация `_hash_embedding` использовала bit-shuffle + `struct.unpack("f", ...)`. Некоторые битовые комбинации дают NaN/inf в IEEE-754. Pgvector режет с `NaN not allowed in vector`.
- После коммита `150f60c` — seed → `random.uniform(-1, 1)`. Детерминированно, никогда NaN.

**Урок 4: Embeddings NaN надо фильтровать ДО insert, не после**
- `VectorStore.add_chunks` теперь проверяет каждый embedding на None/NaN/inf и skip-ит чанк с warn-логом. Если все — `ingest_file` raise-ит `RuntimeError`, router ставит `embedding_status='failed'`. До этого фикса один плохой чанк убивал весь документ.

**Урок 5: Embedding chain (Qwen → Voyage) может вернуть "remaining=0" в логах**
- Это **НЕ** значит chain пустой. Это значит Qwen упал и `_call_with_failover` увидел что `len(self._clients) - self._clients.index(client) - 1 == 0` потому что client.index вернул что Qwen — последний в списке. На самом деле Voyage в chain был. Просто logging misleading.
- Если в логах `remaining=0` после Qwen, **первый** шаг — проверить реально ли Voyage добавлен (`from_settings` или `from_settings_async`).

**Урок 5b: PgBouncer transaction pooling — INSERT проходит, тот же SELECT возвращает 0**
- Корневая причина "embeddings не записываются" в Kamilya на Supabase + PgBouncer.
- `count_in_session=N` после `flush() + commit()` в SQLAlchemy AsyncSession НЕ равен `0`-результату из production — после commit соединение возвращается в pool, и следующий SELECT в той же сессии может получить **другой backend**, который (в зависимости от replication/read-routing) ещё не видит свежезакоммиченные строки.
- **Надёжная проверка** — открыть новую `async with async_session_factory()` сессию и сделать SELECT оттуда (`count_in_fresh`). Это всегда видит committed data.
- Доказательство: локальный repro показал `count_in_session=31`, PgBouncer-овский prod показал `count_in_session=0`, но `count_in_fresh=25` и `SELECT ... FROM psql` показал 25 строк. То есть INSERT реально прошёл — бэк просто не мог это увидеть в своей же сессии.
- Все будущие диагностические SELECT-ы после commit должны идти через **fresh session**, не текущую.

**Урок 5c: Историческая проблема — `chunk_id = md5(text)`**
- Старый код использовал `chunk_id = md5(chunk["text"])` (только текст). Это ломало re-upload: один и тот же текст в двух документах имел одинаковый `chunk_id`, и `ON CONFLICT DO NOTHING` тихо пропускал второй INSERT. Также мог конфликтовать с cross-tenant данными.
- Фикс: `chunk_id = md5(f"{doc_id}|{text}")` — composite id гарантирует уникальность per-document.

---

### Telegram bot webhook — где баги прячутся

**Урок 6: Auth-sessions (Redis) требует UUID-aware JSON encoder**
- `apps/api/app/modules/auth/auth_sessions.py::verify_code` сериализует user_data через `json.dumps(session)`. Если `user_data` содержит UUID (например `tenant_id`) — `json.dumps` падает с `TypeError`.
- Раньше работало случайно: candidate был superadmin (`tenant_id=None`), ветка с UUID не выполнялась. После изменения порядка резолва в telegram.py — candidate = tenant admin, `tenant_id` это UUID, упало.
- **Защита:** есть `_SessionEncoder` (json.JSONEncoder с поддержкой UUID). Любой новый код который пишет user_data в Redis — используй `_dumps()`, не `json.dumps()`.

**Урок 7: User ORM не имеет relationship `tenant`**
- `apps/api/app/models/users.py` не объявляет `tenant` как relationship. Доступ `user.tenant` — AttributeError.
- Раньше работало случайно: superadmin candidate имел `tenant_id=NULL`, ветка с `user.tenant` skip-илась.
- **Защита:** всегда используй `select(Tenant).where(Tenant.id == user.tenant_id)` для получения тенанта. Не пиши `user.tenant`.

---

### Render deploy — где баги прячутся

**Урок 8: autoDeploy не всегда работает**
- Если webhook от GitHub отвалится или сервис был создан вручную в Dashboard до `render.yaml` — push в GitHub не триггерит деплой.
- **Решение:** `RENDER_API_KEY` в env даёт мне (агенту) доступ к Render API. Могу сам триггерить деплой через `POST /v1/services/{id}/deploys`. Если ключа нет — нужно чтобы человек запускал руками через Dashboard.

**Урок 8b: Render CLI v2.20.0 — установлен 2026-06-28**
- Установлен `render` CLI в `$env:USERPROFILE\bin\render.exe`. PowerShell wrapper (`Microsoft.PowerShell_profile.ps1`) автоматически подгружает `RENDER_API_KEY` из `apps/api/.env`.
- **Главное:** CLI даёт доступ к **runtime logs** через `render logs --resources srv-xxx --tail`, что НЕ доступно через REST API (endpoint возвращает 404).
- Также: `render deploys create --wait` стримит deploy logs в реальном времени, `render ssh --ephemeral` для SSH в контейнер.
- Установлены 21 Render agent skill в `~/.agents/skills/` (render-deploy, render-debug, render-cli, render-postgres, render-env-vars, render-log-analysis и др.) — вызываются автоматически когда релевантны.

**Урок 9: Render logs endpoint НЕ доступен через REST API, но ДОСТУПЕН через CLI**
- `GET /v1/services/{id}/logs` возвращает 404. Render даёт логи только через Dashboard UI **или через Render CLI** (`render logs`).
- **Workaround:** `render logs --resources srv-xxx --tail` (live tail), или `render logs --resources srv-xxx --limit 200 --output json --confirm` для batch.
- **Альтернативный workaround (если CLI недоступен):** добавлять `print(..., flush=True)` в production код, чтобы логи шли в stdout (видны в Dashboard → Logs). `logger.info()` может фильтроваться.

**Урок 10: Cloudflare может блокировать твой же IP**
- Bot Fight Mode или WAF rule может заблокировать `python-urllib/3.11` UA с твоего ASN (например `9198` Казахтелеком).
- **Решение:** Cloudflare Dashboard → Security → WAF → Custom Rules → Allow rule для своего IP или Render egress IP. Или переключить DNS на "DNS only" для приватных сервисов (docling.kml.kz).

---

### Многошаговые фичи — паттерн

**Урок 11: При изменении Auth flow — прогоняй ВСЕ три способа логина**
- В Kamilya LMS 3 способа: Telegram-код (через бота), public register (по telegram_id), superadmin email/password. Изменение порядка резолва users в telegram.py сломало оба других способа в разных местах (один получил `tenant_id=UUID` → json.dumps упал, другой получил `tenant_id=None` → ветка skip-илась). Регрессии скрывались за уникальным состоянием каждого user-row.
- **Защита:** smoke-тесты на КАЖДЫЙ сценарий (test_telegram_webhook.py). Перед деплоем фичи которая меняет auth: `pytest tests/test_telegram_webhook.py` локально + хотя бы один integration-test на каждый login path.

---

## Domain context (актуально на 2026-06-26)

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

### LLM / Embeddings fallback chain (added 2026-06-26)
Чтобы LMS не падала когда DGX с Qwen лежит, реализован автоматический failover на cloud-провайдеров. Реализация в `apps/api/app/modules/ai/llm_client.py` (классы `ResilientLLMClient`, `ResilientEmbeddingsClient`).

**LLM chain (по порядку):**
1. **Qwen self-hosted** (`https://qwen.kml.kz/v1`, модель `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit`) — primary, бесплатно
2. **DeepSeek v4-flash** (`https://api.deepseek.com/v1`, модель `deepseek-v4-flash`) — fallback, $0.14/$0.28 per 1M tokens. Ключ `DEEPSEEK_API_KEY` в env или в БД. **ВАЖНО:** `deepseek-chat` deprecated 2026-07-24 — НЕ использовать старое имя.

**Embeddings chain (по порядку):**
1. **Qwen self-hosted** (`https://qwen-embed.kml.kz/v1`, модель `Qwen3-Embedding-8B`) — primary
2. **Voyage voyage-4-lite** (`https://api.voyageai.com/v1`) — fallback, $0.02/M с **200M бесплатных токенов** на аккаунт. Ключ `VOYAGE_API_KEY` в env или в БД.

**Resolution priority (для каждого провайдера):**
1. Environment variable (`DEEPSEEK_API_KEY` / `VOYAGE_API_KEY`) — перекрывает всё
2. Active global key в таблице `provider_keys` (superadmin-managed)
3. Provider skipped from chain

Production hot-path вызывает `ResilientLLMClient.from_settings_async()` / `ResilientEmbeddingsClient.from_settings_async()` (async!) — они читают ключи из БД через `_resolve_db_key()`. Sync `from_settings()` оставлен только для тестов и legacy (читает только env).

**Что НЕ включено в v1:**
- ❌ OpenRouter (через него можно добавить Claude Haiku как 4-й tier для reviewer — отложено до отдельного epic)
- ❌ Quality-tier для reviewer (DeepSeek v4-pro / Claude) — отложено
- ❌ Per-tenant provider keys (сейчас только global, tenant_id=NULL). Архитектура таблицы это поддерживает, нужен только UI

### Provider keys UI (superadmin) — added 2026-06-26
URL: `/admin/providers` (только для роли `superadmin`). Backend: `apps/api/app/modules/admin/provider_keys/`.

**Endpoints:**
- `GET    /v1/admin/provider-keys` — список ключей (masked preview)
- `POST   /v1/admin/provider-keys` — создать ключ (encrypt через Fernet перед insert)
- `PATCH  /v1/admin/provider-keys/{id}` — изменить label / api_key / is_active
- `DELETE /v1/admin/provider-keys/{id}` — удалить
- `POST   /v1/admin/provider-keys/{id}/test` — ping провайдера для проверки ключа

**Шифрование:** Fernet с мастер-ключом `PROVIDER_KEY_ENCRYPTION_KEY` в env. Потеря этого ключа = все ключи в БД нерасшифровываемы. Хранить offline backup в password manager.

**Если фича добавляет нового провайдера:**
- Добавь config в `app/core/config.py`
- Добавь factory `_xxx_provider()` в `llm_client.py` возвращающий `LLMProviderConfig | None`
- Включи его в chain через `from_settings_async()` (только если ключ есть в env или БД)
- Добавь provider name в enum/validator в `admin/provider_keys/schemas.py`
- Покрой тестами в `tests/test_llm_failover.py` и `tests/test_provider_keys.py`
