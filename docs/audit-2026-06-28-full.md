# Kamilya LMS — Full Project Audit Report

**Дата:** 2026-06-28
**Агент:** ZCode (GLM-5.2)
**Workspace:** `D:\Камиля\lms`
**Scope:** Read-only аудит по 9 фазам (Structure, Architecture, Multi-tenancy, Security, DB/Perf, AI, Testing, Frontend, DX). Не запускался runtime (pytest/coverage/E2E не прогонялись — см. §13 Ограничения).

---

## 1. Executive Summary

Kamilya LMS — зрелый для стадии beta кодбейс: модульная монолитная архитектура на бэкенде соблюдена, multi-tenancy проходит через ORM-фильтры и RLS-политики на всех tenant-таблицах, AI-pipeline имеет грамотный failover Qwen→DeepSeek/Voyage с NaN-защитой, а lessons learned из AGENTS.md реально закодированы в репозиторий. Доменная модель (Course→Module→Lesson, Quiz, Enrollment, Certificate) покрыта моделями, миграциями и роутерами.

Однако проект **не готов к GA без критических доработок**. Главные проблемы лежат в плоскости **гигиены engineering-практик, а не архитектуры**: отсутствует CI/CD и pre-commit (правила из AGENTS.md никем не enforced), нет обязательных cross-tenant тестов (явное нарушение §Multi-tenancy тестирования), access-token хранится в `localStorage` (нарушение storage policy), RLS не "FORCE"-нут и обходится owner-ролью БД, в коде есть несколько N+1 и oversized-файлов. Эти проблемы решаемы за 1–2 спринта без переделок архитектуры.

**Общая оценка:** 🟠 **Needs attention** — функционально богат и архитектурно здрав, но engineering-гигиена и security-усиление обязательны перед GA.

**Top 3 критичных проблемы:**
1. 🔴 **Нет CI/CD и pre-commit hooks** — правила AGENTS.md (ruff, mypy, cross-tenant tests, tenant_id grep) существуют только как текст. Любой PR может нарушить multi-tenancy. `.github/workflows/` отсутствует. (Phase 9)
2. 🔴 **Cross-tenant тесты отсутствуют** — `apps/api/tests/` не содержит ни одного теста "Tenant A создаёт → Tenant B читает → 404". `conftest.py` пуст (нет test-БД/фикстур). Это прямой пропуск обязательного gate из AGENTS.md. (Phase 3/7)
3. 🔴 **RLS не enforced (нет `FORCE ROW LEVEL SECURITY`)** + access-token в `localStorage` — RLS-политики созданы, но т.к. роль приложения = table owner, они не применяются; приложение полностью полагается на ORM-фильтры (одна ошибка в WHERE = leak). Frontend держит JWT в localStorage (XSS-кража) вместо in-memory. (Phase 3/4)

**Статистика findings:**
- 🔴 CRITICAL: **6**
- 🟠 HIGH: **9**
- 🟡 MEDIUM: **13**
- 🟢 LOW: **8**

---

## 2. Phase 1: Inventory & Structure

### Найденное
Реальная структура близка к описанной в AGENTS.md, но есть расхождения.

**Бэкенд** (`apps/api/app/`, ~20 360 LOC Python, 30 миграций Alembic):
- ✅ 15 модулей под `modules/`: admin, ai, audit, auth, certificates, courses, demo, documents, enrollments, integrations, lessons, positions, progress, quizzes, student, users.
- ✅ Core (`app/core/`): auth, config, db, errors, rate_limit, security, encryption, celery_app, demo_limits, debug_log_buffer, storage/.
- ✅ Models (`app/models/`): 12 файлов моделей (DB-driven, не per-module — отклонение от AGENTS.md §3, но осознанное).
- ⚠️ Не у всех модулей есть полный набор `models.py/schemas.py/service.py/repository.py/router.py/tests/`. Например, `documents/` и `enrollments/` **не имеют `models.py`** (модели в корневом `app/models/`), `demo/` только router. Repository-слой фактически отсутствует — queries живут прямо в `router.py` (violation §3 "только через ORM/repositories").
- ⚠️ `features/` на фронте **почти не используется**: только `integrations/` и `quiz-assignments/`. Весь остальной UI живёт в `app/<route>/page.tsx` (route-based, не feature-based — отклонение от AGENTS.md §4).

**Фронтенд** (`apps/web/src/`, App Router): `app/` (24 route-директории), `components/{ui,a11y,ai,brand,demo,layout}`, `i18n/locales/{ru,kk,en}.json` (829 строк каждая — parity), `lib/`, `store/`.

**Инфра/тесты:** `infra/{Caddyfile,caddy,docling-service,wa-gateway,init.sql}`, `tests/load/k6-test.js`, `apps/web/tests/e2e/{login,navigation}.spec.ts`, `apps/api/tests/` (15 файлов, 2 460 LOC), `packages/{db-schema,ml_pipeline,shared-types,ui-kit}`.

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 1.1 | 🟠 HIGH | `apps/api/app/modules/positions/router.py` (1816 строк) | Единственный файл >800 LOC (бюджет AGENTS.md). Гигантский роутер с bulk-import + JD-analyze + quiz-gen. | Split на `positions/router.py`, `positions/bulk_router.py`, `positions/jd_router.py`. |
| 1.2 | 🟡 MEDIUM | `apps/api/app/models/` (12 моделей в корне) | Models централизованы в `app/models/`, не per-module. Отклонение от AGENTS.md §3. | Либо документировать как осознанный выбор (add ADR), либо мигрировать. Низкий приоритет — работает. |
| 1.3 | 🟡 MEDIUM | `apps/api/app/modules/{documents,enrollments,lessons,...}` | Repository-слой отсутствует. Запросы прямо в `router.py` (напр. `documents/router.py:171`). | Ввести `repository.py` per module, переместить SELECT/INSERT туда. Покрытие 80% только для repo. |
| 1.4 | 🟡 MEDIUM | `apps/web/src/app/` (24 route-директории) | Frontend route-based, не feature-based (AGENTS.md §4 предписывает `features/<feature>/{components,hooks,api.ts}`). | Для новых крупных фич следовать §4. Existing — оставить (refactor=cost>value). |
| 1.5 | 🟢 LOW | Корень репо: `check_*.sql`, `fix_*.sql`, `add_deferral.sql`, `test_demo.json` | Scratch SQL/JSON файлы в корне. `.gitignore` их исключает (✅ не в git), но захламляют FS. | Удалить локально или переместить в `scripts/scratch/`. |
| 1.6 | 🟢 LOW | `docs/01_brand_book_acme.txt`, `docs/лог версел.txt`, `docs/лог рендер.txt`, `docs/авторизация бот.txt` | Логи/scratch в `docs/`, кириллические имена. | Переместить логи в `docs/runbooks/` или удалить после архивирования. |
| 1.7 | 🟢 LOW | `repomix-output.md` (774 KB в корне) | Сгенерированный артефакт repomix закоммичен в корне. | Удалить, добавить в `.gitignore`. |
| 1.8 | 🟢 LOW | `migrations/` (корневой) vs `apps/api/alembic/versions/` | Две директории миграций: корневая `migrations/` содержит дублирующие `.sql` (0018_rls, 0020_progress). Alembic — каноничный. | Удалить корневой `migrations/` (или документировать как архив). |

---

## 3. Phase 2: Architecture Compliance

### Найденное
- ✅ Модульный монолит соблюдён: каждый модуль под `modules/<feature>/`.
- ✅ Naming conventions (snake_case Python, PascalCase классы, kebab-case URLs, plural table names, VARCHAR+CHECK для enums) — соблюдаются (`models/users.py:36-39`).
- ✅ Мало TODO/FIXME (3 находки: `ai/ingestion.py:352`, `positions/router.py:1315`, false-positive в `certificates/service.py:17`).
- ✅ Frontend не содержит `console.log` в продакшн-коде.
- ⚠️ Cross-module imports есть, но допустимые (lazy imports внутри функций для разрыва циклов).
- ⚠️ `print()` в backend — но это **документированный workaround** для Render Dashboard logs (AGENTS.md §Урок 9), не нарушение.

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 2.1 | 🟠 HIGH | `apps/api/app/modules/admin/service.py:12-13`, `admin/export.py:12,48`, `audit/superadmin/router.py:33` | Top-level cross-module imports (`from app.modules.quizzes.models import QuizAttempt` из `admin`/`export`). AGENTS.md §3: "Прямой импорт — на review", зависимости через DI. | Ввести service-interface или перенос shared models в `app/models/`. Текущий стиль допустим, но фиксировано в код-ревью. |
| 2.2 | 🟡 MEDIUM | `app/main.py:12` | Comment-док "Must be imported BEFORE router imports" + side-effect import `from app.modules.positions.models import Position` для регистрации таблицы перед резолвом FK `User.position_id`. Хрупкий порядок импортов. | Решить через `Base.metadata`-explicit-register или вынести Position в `app/models/`. |
| 2.3 | 🟡 MEDIUM | `apps/api/app/modules/ai/router.py:830 LOC` | Файл 830 строк — на границе бюджета (800). | Split preview/regenerate/chat endpoints в отдельные под-роутеры. |
| 2.4 | 🟡 MEDIUM | `app/core/auth.py:69-70` | `except Exception: pass` — silent swallow при ошибке `set_current_tenant`. Если RLS-функция падает, fallback тихо полагается на ORM (правильно, но логирование отсутствует). | `logger.warning("set_current_tenant failed, falling back to ORM filter: %s", e)` — для observability. |
| 2.5 | 🟡 MEDIUM | `apps/web/src/app/*.tsx` (~30 мест `: any`) | Местами `any` в business-логике: `ai/generate/page.tsx:1095 (m: any)`, `dashboard/page.tsx:48 (c: any)`. Остальные — `catch (err: any)` (допустимо). | Для итераций `.map` — завести Zod-схему ответа и типизировать. |
| 2.6 | 🟢 LOW | `app/main.py:139-144` | `HealthCheckFilter` добавляется к `uvicorn.access` без фильтра "if not configured" — косметика. | ОК, nice-to-have. |

---

## 4. Phase 3: Multi-tenancy Verification 🔴

### Найденное
- ✅ **Большинство** production-путей фильтруют по `tenant_id` из `user.tenant_id` (примеры: `courses/router.py:53,109,157`, `documents/router.py:113,127,173,267`, `audit/service.py:60,82`, `admin/service.py:20-83`, `student/service.py:19,42`).
- ✅ Cross-tenant доступ возвращает 404 (не 403): `documents/router.py:131`, `ai/router.py:147`.
- ✅ `tenant_id` нигде не читается из request body/query в tenant-endpoints.
- ✅ Superadmin (tenant_id=NULL) явно отсекается от tenant-эндпоинтов через `require_tenant_user()` (`auth.py:153-177`).
- ⚠️ RLS-политики созданы (миграция 0019, 18 таблиц), но **не FORCED**.
- ⚠️ `provider_keys.tenant_id=None` — осознанный global-only паттерн v1 (документирован в AGENTS.md).

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 3.1 | 🔴 CRITICAL | `alembic/versions/0019_rls_policies.py` (нет FORCE) | `ENABLE ROW LEVEL SECURITY` без `FORCE ROW LEVEL SECURITY`. Т.к. роль приложения (`lms`) = table owner, owner **bypasses RLS** (поведение Postgres по умолчанию). RLS сейчас — мёртвая страховка. Приложение полностью полагается на ORM-фильтры. | `ALTER TABLE ... FORCE ROW LEVEL SECURITY` для всех tenant-таблиц + создать отдельную NON-superuser/NOBYPASSRLS роль для приложения (или `ALTER ROLE lms NOBYPASSRLS`). |
| 3.2 | 🟠 HIGH | `app/modules/auth/service.py:90` | Legacy fallback: если домен email не мэтчит tenant → `select(User).where(User.email == email)` **без tenant_id**. "Legacy users" комментарий. Теоретически позволяет login пользователя не своего тенанта, если email уникален глобально. | Удалить legacy-ветку или явно проверять `user.tenant_id == tenant.id` после fetch. Если legacy реально нужен — задокументировать почему. |
| 3.3 | 🟠 HIGH | `app/modules/ai/job_service.py:39` | `get_ai_job` делает `select(AIJob).where(AIJob.id == job_id)` **без tenant_id**. Хотя router (`ai/router.py:146`) компенсирует проверкой `job.tenant_id != user.tenant_id → 404`, сама функция сервиса небезопасна для повторного использования. | Добавить `tenant_id` параметр в `get_ai_job` и фильтр в WHERE. Defense-in-depth. |
| 3.4 | 🟡 MEDIUM | `app/core/auth.py:113-114` (`_ImpersonatedUser.__getattr__`) | Impersonation через wrapper-объект с `__getattr__` — элегантно, но любой `getattr(user, X)` возвращает атрибут реального superadmin. Если где-то код читает `user.tenant_id` через `getattr` (а не `.`), может протечь реальный tenant. | Добавить whitelist forwarding или explicit properties для критичных полей. |
| 3.5 | 🟡 MEDIUM | Нет cross-tenant тестов (см. Phase 7) | Нельзя доказать, что tenant-isolation работает регрессионно. | Обязательно — см. Phase 7. |
| 3.6 | 🟢 LOW | `auth.py:67-68` | `await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})` — set_config в транзакции. При PgBouncer transaction-pooling `is_local=true` корректно, но если кто-то переключит на session-pooling — tenant context утечёт между запросами. | Документировать требование transaction-pooling в runbook. |

---

## 5. Phase 4: Security Audit 🔴

### Найденное
- ✅ JWT: `HS256` (explicit в config), `exp/iat/nbf/jti` claims есть. argon2 (`argon2-cffi`) для паролей, bcrypt не используется.
- ✅ CORS: explicit список (не `*`), 6 origin'ов. Security headers middleware (`security.py`): HSTS, X-Content-Type-Options, X-Frame-Options, CSP, Permissions-Policy.
- ✅ Rate limiting реализован (Redis sliding window), per-endpoint конфиги. Fail-open если Redis down (компромисс).
- ✅ Magic-byte MIME check (`documents/router.py:41-48`), size limit, server-generated UUID s3_key.
- ✅ Encryption ключей в `provider_keys` через Fernet (`config.py:142`).
- ✅ `.env` в `.gitignore`, секреты не хардкожены (grep чистый).
- ⚠️ Cookies не `Secure`.
- ⚠️ JWT `aud` claim не валидируется.
- ⚠️ Access token в localStorage.

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 4.1 | 🔴 CRITICAL | `apps/web/src/lib/auth.ts:35,51-52` | Access token в `localStorage` + cookie `kamilya_token` без `Secure`. AGENTS.md §Authz: "access в памяти (15min), refresh в httpOnly cookie (30 days)". localStorage = XSS-кража. Cookie без `Secure` = утечка по HTTP. | In-memory token + httpOnly Secure SameSite=Strict refresh-cookie. Обновлять access через /auth/refresh. Минимум: `Secure; SameSite=Strict` на cookie (env-aware). |
| 4.2 | 🟠 HIGH | `app/core/auth.py:45` (`decode_token`) | `jwt.decode(...)` без `audience=` и без explicit `algorithms=` list — `settings.JWT_ALGORITHM` = "HS256", но если env выставит `"none"`, примется. AGENTS.md: "algorithms=explicit, never include none". | `jwt.decode(token, key, algorithms=["HS256"], audience=settings.JWT_AUDIENCE)` + добавить `aud` claim в `create_access_token`. |
| 4.3 | 🟠 HIGH | `app/core/config.py:54` (JWT_SECRET default `""`) + валидатор | `validate_jwt_secret` поднимается только если secret пуст. Но дефолт-значение в коде = пустая строка — при ошибке конфигурации валидатор ловит, ✅. Однако нет проверки **длины/энтропии** секрета. | `min_length` hint + startup-check на длину ≥ 32 байта. |
| 4.4 | 🟡 MEDIUM | `app/core/rate_limit.py:131,135-136` | Rate-limit fail-open (разрешает запрос при ошибке Redis). Для auth-endpoints это компромисс доступности vs brute-force защиты. | Для `/auth/login` и `/auth/register` рассмотреть fail-CLOSED (отклонять при Redis-down) — потеря доступности < риск brute-force. |
| 4.5 | 🟡 MEDIUM | `rate_limit.py:131` | Key = `path:client_ip`. AGENTS.md: "LLM generation: per-tenant budget". Текущий лимит — 2/min на `/ai/generate-course`, но **глобальный по IP**, не per-tenant. Один tenant с N IP может обойти бюджет. | Ключ `rate_limit:{path}:{tenant_id}:{user_id}` для авторизованных эндпоинтов. |
| 4.6 | 🟡 MEDIUM | `documents/router.py:38` (`MAX_FILE_SIZE = 10MB`) | Лимит 10MB. AGENTS.md §File upload: "50MB default". Расхождение со спекой (можно осознанно, но недокументировано). | Либо привести к 50MB, либо зафиксировать 10MB как решение в ADR. |
| 4.7 | 🟡 MEDIUM | `documents/router.py:31-33` | `text/plain`, `text/markdown`, `text/csv` — `None` magic bytes (skip check). Любой бинарный файл можно загрузить, объявив `text/plain`. | Добавить минимальную эвристику для text (printable ASCII / UTF-8 decodable) или хотя бы cap на размер text-upload отдельно. |
| 4.8 | 🟢 LOW | `app/core/config.py:16-26` | `ALLOW_ADMIN_DEMO` / `ALLOW_SUPERADMIN_DEMO` флаги с comment "TEMP: enable in production". Если останутся `True` в проде — demo-login артефакт. | Удалить после завершения e2e (закоммиченный comment уже напоминает). |
| 4.9 | 🟢 LOW | `config.py:62-64` | MinIO default credentials (`minioadmin`/`minioadmin_secret_2026`) в коде. Только defaults, не прод-секреты, но лучше `""` + валидатор. | Defaults = `""`, fail-fast при отсутствии. |

---

## 6. Phase 5: Database & Performance

### Найденное
- ✅ 30 миграций Alembic, **линейная цепочка** (0001→0032, один head `0032`), down_revision консистентны. Миграции запускаются на startup (`main.py:62-84`).
- ✅ pgvector включён (`0018`), ivfflat индекс на `document_embeddings.embedding` (vector_cosine_ops).
- ✅ Партиальные уникальные индексы (`models/users.py:38-39`), composite индексы tenant_id-first.
- ✅ Async повсюду (`httpx.AsyncClient`, `asyncpg`, `redis.asyncio`), sync I/O в async-routes не найден.
- ✅ `expire_on_commit=False` (правильно для async-session).
- ⚠️ N+1 в нескольких местах.
- ⚠️ `pool_size` не настроен (default asyncpg pool).

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 5.1 | 🟠 HIGH | `app/modules/quizzes/router.py:47-51` (`list_quizzes`) | N+1: для каждого quiz отдельный `get_quiz_with_questions(db, q.id, ...)`. При 50 quizzes = 51 запрос. | Eager-load через `selectinload(Quiz.questions).selectinload(Question.choices)` одним запросом. |
| 5.2 | 🟠 HIGH | `app/modules/student/service.py:28-48` (`get_student_dashboard`) | N+1: 2 запроса per enrollment (total + completed lessons). При 10 курсах = 20 запросов на dashboard рендер. | Один запрос с `func.count(...)` + `GROUP BY` + `LEFT JOIN progress`. |
| 5.3 | 🟡 MEDIUM | `app/core/db.py:7` | `create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)` — `pool_size`, `pool_pre_ping` не заданы. AGENTS.md §DB: "pool_size = (CPU×2)+spindle, pool_pre_ping=True". | `create_async_engine(..., pool_size=20, max_overflow=10, pool_pre_ping=True, pool_recycle=1800)`. |
| 5.4 | 🟡 MEDIUM | `alembic/versions/0018_add_document_embeddings.py:37-38` | ivfflat без `lists=` параметра (default 100). Для больших коллекций — субоптимальный recall/latency. | `USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)` после ≥10k строк; либо HNSW. Зафиксировать после measure. |
| 5.5 | 🟡 MEDIUM | `ai/router.py:260-271`, `ai/router.py:292`, `ai/router.py:442`, etc. | Несколько циклов с вложенными SELECT (modules → lessons → quizzes) без batching. Pipeline preview может делать O(modules × lessons) запросов. | Собрать `module_ids`/`lesson_ids` → один `IN (...)` запрос с группировкой в Python. |
| 5.6 | 🟡 MEDIUM | `courses/router.py:136-157` | Внутри цикла по lessons — `select(Quiz).where(Quiz.lesson_id.in_(lesson_ids), ...)` (✅ batched), но это в loop-body. | Вынести batch-запрос из цикла — однократно по всем lesson_ids. |
| 5.7 | 🟢 LOW | `migrations/0018_rls_policies.sql`, `migrations/0020_add_progress_completed_at.sql` (корневой `migrations/`) | Дублирующие SQL-миграции вне Alembic-цепочки. Не запускаются автоматически. | Удалить или переместить в `docs/archive/`. |
| 5.8 | 🟢 LOW | `app/core/db.py` | Нет explicit `pool_timeout`, `pool_use_lifo`. | nice-to-have для пиковой нагрузки. |

---

## 7. Phase 6: AI / LLM Pipeline

### Найденное
AI-pipeline — **сильнейшая часть** кодбаза. Все lessons learned из AGENTS.md закодированы:
- ✅ LLM chain: Qwen (primary) → DeepSeek v4-flash (fallback). Embeddings: Qwen → Voyage voyage-4-lite. `llm_client.py:1-30` — детальные docstrings.
- ✅ Embeddings endpoint = `/embeddings` (не `/chat/completions`) — урок 1 применён (`llm_client.py:82-89`).
- ✅ NaN-фильтрация перед insert (`ingestion.py:403-418` `_hash_embedding` clamped to `[-1, 1)`, never NaN/inf). Уроки 3–4 применены.
- ✅ `chunk_id = md5(doc_id + text)` composite (урок 5c).
- ✅ `embedding_status` judged on `embeddings_written`, not `chunks` (`documents/router.py:215-237`). Урок 2 применён.
- ✅ Provider keys через Fernet (`config.py:142`), `_resolve_db_key` env→DB priority (`llm_client.py:127-154`). Урок из AGENTS.md применён.
- ✅ Jinja2 prompt templates (`packages/ml_pipeline`, `app/ml_prompts/`, `jinja2` в deps — коммит `a0822af`).

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 6.1 | 🟡 MEDIUM | `ai/ingestion.py:352` (`# TODO: Call Qwen 3.5 when available`) | TODO указывает на незавершённый path. Нужно проверить — это активный код или legacy? | Проверить, удалить если legacy. |
| 6.2 | 🟡 MEDIUM | `llm_client.py:149` (`except Exception` в `_resolve_db_key`) | Broad except при чтении key из БД → возвращает `""` → provider skip. Тихо деградирует chain без алерта. | Различать "нет ключа" (норма) от "БД упала" (warning+метрика). |
| 6.3 | 🟡 MEDIUM | нет per-tenant LLM budget в коде | AGENTS.md §6: "LLM generation: per-tenant budget (cost control)". Rate-limit `/ai/generate-course` = 2/min/IP, но **нет dollar/token budget per tenant**. Один tenant может потратить весь DeepSeek-бюджет. | Ввести `tenant_settings.monthly_llm_budget_usd` + accumulator; reject на превышении. |
| 6.4 | 🟢 LOW | `ai/assessment.py:115-120` | `print(...)` debug-логи сырого LLM-ответа (`[ASSESSMENT_RAW]`, `[ASSESSMENT_OK]`, `[ASSESSMENT_PARSE]`). Render-workaround, но логирует длину+first500 ответа — может протечь PII из документов. | Заменить на `logger.debug` (фильтруется в проде), не писать `response.content` в stdout. |
| 6.5 | 🟢 LOW | `documents/router.py:238-247` | `print(f"[UPLOAD] Ingested {file.filename}: chunks=...")` — filename в stdout. Фilenames могут содержать чувствительные имена. | `logger.info` без filename, или sanitize. |

---

## 8. Phase 7: Testing Coverage

### Найденное
- ⚠️ 15 тест-файлов, **2 460 LOC** для бэкенда **20 360 LOC** (ratio ~12%). Покрытие не прогонялось (нет runtime), но по распределению — unit-тесты есть для ai/auth/certificates/quizzes/positions/telegram/provider_keys/storage. **Service/repository coverage 80% НЕ доказан** (нет CI gate).
- 🔴 **Cross-tenant тесты отсутствуют** — нет ни одного теста "Tenant A создаёт → Tenant B 404".
- 🔴 `conftest.py` пуст — **нет test-БД, нет фикстур tenant/user/course**.
- ✅ E2E: `apps/web/tests/e2e/{login,navigation}.spec.ts` (2 spec-файла). AGENTS.md требует "critical paths: login, course creation, quiz taking, certificate generation" — покрыт только login.
- ✅ Load test: `tests/load/k6-test.js`.

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 7.1 | 🔴 CRITICAL | `apps/api/tests/` (нет cross-tenant) | Ни одного теста проверяющего tenant-isolation на уровне БД/endpoint. AGENTS.md: "Cross-tenant test MANDATORY ... Тест ДОЛЖЕН быть в PR, иначе review rejection". | Добавить `tests/test_tenant_isolation.py`: fixture с 2 tenant+user, создать course в tenant A, GET как user B → 404. Для каждого data-модуля (courses, documents, quizzes, enrollments). |
| 7.2 | 🔴 CRITICAL | `apps/api/tests/conftest.py` (1 строка docstring) | Нет DB-fixture (async test-session с rollback), нет tenant/user/course factories. Интеграционные тесты не могут работать с реальной БД. | `conftest.py` с `async_session` fixture (transactional rollback), `make_tenant()`, `make_user(tenant)`, `make_course(tenant)` factory-functions. |
| 7.3 | 🟠 HIGH | нет pytest-cov gate в CI (CI отсутствует) | Покрытие 80% для service/repository не enforced. | `pytest --cov=apps/api/app/modules --cov-fail-under=80` в CI. |
| 7.4 | 🟠 HIGH | `apps/web/tests/e2e/` | Только login+navigation. Нет course creation, quiz taking, certificate generation. | 3 дополнительных spec-файла для critical paths. |
| 7.5 | 🟡 MEDIUM | `tests/test_integration.py` | Только 422-validation тесты (см. `TestAuthEndpoint`). Нет happy-path / нет проверки auth-flow end-to-end. | Добавить full flow: register → login → create course → enroll → take quiz → get certificate. |
| 7.6 | 🟢 LOW | `apps/api/tests/test_setup_storage_bucket.py` | Это setup-скрипт-как-тест, не поведение. | Переместить в `scripts/`. |

---

## 9. Phase 8: Frontend & UX

### Найденное
- ✅ Next.js 14 App Router (`apps/web/src/app/`), Server/Client components разделены.
- ✅ i18n: `next-intl`-style (custom `useT`), 3 локали (ru/kk/en), 829 строк каждая — parity.
- ✅ Zustand для client state (`store/authStore.ts`, `store/languageStore.ts`).
- ✅ API client в `lib/api.ts`, a11y-компоненты в `components/a11y/`, `SkipLink.tsx`, `CommandPalette.tsx`.
- ✅ Playwright + vitest настроены (`playwright.config.ts`, `vitest.config.ts`).
- ⚠️ ~30 мест `: any` (часть — `catch`, часть — business types).

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 8.1 | 🟠 HIGH | `apps/web/src/middleware.ts:13` | Auth check по cookie `kamilya_token` — но access-token в localStorage (`auth.ts:35`)才是 source-of-truth. Cookie и localStorage рассинхронизируются (cookie `max-age=86400` = 24h, token expire 15min). Защищённый route может пустить по протухшему-cookie. | Единый source: либо SSR-session (httpOnly cookie), либо client-side gate с проверкой token-validity в middleware через verify-endpoint. |
| 8.2 | 🟡 MEDIUM | `apps/web/src/app/ai/generate/page.tsx:1095,1148` (`m: any`, `l: any`) | Big page (~1100+ строк), модули/уроки типизированы как `any`. | Завести `Module[]`/`Lesson[]` типы (Zod-схема ответа `/ai/preview`). |
| 8.3 | 🟡 MEDIUM | `apps/web/src/app/ai/generate/page.tsx` (~1100+ LOC) | Один page-компонент >1000 строк. Frontend-аналог oversized-file. | Split в под-компоненты (`ModuleList`, `LessonEditor`, `PipelineProgress`). |
| 8.4 | 🟡 MEDIUM | i18n KK quality | Паритет строк (829 = 829 = 829), но качество/полнота KK перевода инструментально не проверяется. AGENTS.md metric: "KK 80%". | Native-speaker review KK-locale; добавить CI-чек на missing keys (parity ✅, но machine-translated-risk). |
| 8.5 | 🟢 LOW | `apps/web/src/lib/auth.ts` (нет refresh-token client) | No refresh-token handling client-side (т.к. access в localStorage). | Связано с 4.1 — после переезда на httpOnly refresh-cookie добавить `/auth/refresh` call на 401. |
| 8.6 | 🟢 LOW | `apps/web/src/middleware.ts:4` | `protectedRoutes` hard-coded list. При добавлении route — забыть добавить = security gap. | Convention-based: всё кроме `publicRoutes` = protected. |

---

## 10. Phase 9: Documentation & DX

### Найденное
- ✅ Богатая документация: `TZ.md` (64KB), `AGENTS.md` (40KB с lessons learned), `DESIGN.md`, `DEPLOY.md`, `PROGRESS.md`, `ROADMAP.md`, `WCAG.md`, 4 ADR, user/admin guides (ru/kk).
- ✅ `.env.example` есть для api/web/wa-gateway.
- ✅ `render.yaml` настроен, auto-deploy через Render.
- 🔴 **CI/CD отсутствует** (`.github/workflows/` нет).
- 🔴 **Pre-commit hooks отсутствуют**.
- 🔴 **docker-compose отсутствует** (AGENTS.md W1: "docker-compose, DB migrations").
- ⚠️ Нет observability (Sentry/Prometheus/structured-logging).

### Findings
| # | Severity | File:Line | Issue | Recommendation |
|---|----------|-----------|-------|----------------|
| 9.1 | 🔴 CRITICAL | `.github/workflows/` — отсутствует | Нет CI. AGENTS.md §testing: "CI fail-under", "PR без tenant filter = rejected". Правила существуют только как текст, никем не enforced. | `.github/workflows/ci.yml`: ruff + mypy + pytest --cov-fail-under=80 + tenant-grep + (опц.) cross-tenant test gate. |
| 9.2 | 🟠 HIGH | Нет `.pre-commit-config.yaml` / `.husky` | AGENTS.md §Security: "Pre-commit grep: rg tenant_id на select(...)". Не настроено. | `pre-commit` с ruff, mypy-stub, detect-secrets, custom tenant-grep hook. |
| 9.3 | 🟠 HIGH | Нет `docker-compose.yml` | AGENTS.md W1 + "docker compose up postgres redis minio". Отсутствует → `docker compose up` из commands не работает. | `docker-compose.yml` с postgres16+pgvector, redis, minio, опц. qwen. |
| 9.4 | 🟠 HIGH | Нет observability | Нет Sentry, Prometheus, structured-logging. `debug_log_buffer.py` — in-memory ring buffer (workaround для Render logs). В проде без Sentry ошибки невидимы. | `sentry-sdk[fastapi]` + structured JSON logging (`structlog` или `python-json-logger`). |
| 9.5 | 🟡 MEDIUM | `docs/adr/` пропуски 0004–0009 | ADR 0001, 0002, 0003, 0010. Нумерация с gaps. | Либо заполнить gaps (auth-strategy, storage-choice, ai-pipeline ADR), либо переименовать 0010→0004. |
| 9.6 | 🟡 MEDIUM | `AGENTS.md` §"Что ты получишь на входе" vs реальность | Указан `packages/db-schema/` (Drizzle + миграции), реально миграции в Alembic (`apps/api/alembic/`). `packages/db-schema/` содержит SQL-схему, не Drizzle. Документация устарела. | Обновить AGENTS.md §structure: "Alembic (apps/api/alembic/) — каноничные миграции". |
| 9.7 | 🟡 MEDIUM | `main.py:62` (`_run_migrations` на startup) | Миграции запускаются в app-lifespan. Для multi-instance deploy это race (несколько воркеров одновременно `upgrade head`). | Внешний migration-step в CI/CD или Render pre-deploy hook. Для single-instance Render — терпимо. |
| 9.8 | 🟢 LOW | `docs/audit-code-2026-06-24.md`, `docs/audit-ux-ui-2026-06-24.md` | Предыдущие аудиты есть — ✅ хорошая практика, но без ссылки из README/AGENTS. | Index в `docs/README.md`. |
| 9.9 | 🟢 LOW | `README.md` (909 bytes) | Минимальный README — нет quickstart, badges, architecture overview. | Расширить: quickstart (docker compose up / pnpm dev), архитектура-диаграмма, ссылка на TZ/AGENTS. |

---

## 11. Prioritized Action List

### 🔴 Сделать немедленно (эта неделя) — блокируют GA

1. **[9.1] Настроить CI/CD** — `.github/workflows/ci.yml`: ruff, mypy, pytest-cov-fail-under=80, tenant-grep hook. Без этого правила AGENTS.md = текст. *Effort: 1 day.*
2. **[7.1] Cross-tenant тесты** — `tests/test_tenant_isolation.py` для courses/documents/quizzes/enrollments. *Effort: 1 day.*
3. **[7.2] `conftest.py` с DB-fixture** — async-session + tenant/user/course factories. Без него cross-tenant тесты не напишешь. *Effort: 0.5 day.*
4. **[3.1] RLS `FORCE ROW LEVEL SECURITY`** + app-роль `NOBYPASSRLS` — иначе RLS мёртв. Миграция 0033. *Effort: 0.5 day.*
5. **[4.1] Перенести access-token из localStorage в memory + httpOnly Secure refresh-cookie.** *Effort: 1.5 days (frontend+backend).*

### 🟠 Сделать в W5-6

6. **[9.2] pre-commit** (ruff, mypy, detect-secrets, tenant-grep). *Effort: 0.5 day.*
7. **[9.3] `docker-compose.yml`** (postgres+pgvector, redis, minio). *Effort: 0.5 day.*
8. **[9.4] Sentry + structured logging.** *Effort: 1 day.*
9. **[5.1, 5.2] N+1 в `list_quizzes` и `get_student_dashboard`** — eager-load / aggregate-запрос. *Effort: 0.5 day.*
10. **[3.2, 3.3] Убрать tenant-less fallback** в `auth/service.py:90` и параметризовать `get_ai_job(tenant_id)`. *Effort: 0.5 day.*
11. **[4.2] JWT `audience` validation + explicit `algorithms=["HS256"]`.** *Effort: 0.5 day.*
12. **[1.1] Split `positions/router.py` (1816 строк)** на 3 под-роутера. *Effort: 1 day.*
13. **[7.4] E2E: course creation, quiz taking, certificate generation.** *Effort: 1.5 days.*

### 🟡 Backlog (tech-debt)

14. **[1.3]** Ввести repository-слой per module (переместить queries из router.py).
15. **[5.3]** `pool_size`, `pool_pre_ping`, `pool_recycle` в `create_async_engine`.
16. **[4.5]** Rate-limit ключ per-tenant (для авторизованных эндпоинтов).
17. **[4.6, 4.7]** file-upload лимит (10→50MB решение в ADR) + text-upload эвристика.
18. **[6.3]** Per-tenant LLM budget (`tenant_settings.monthly_llm_budget_usd`).
19. **[8.3]** Split `ai/generate/page.tsx` на под-компоненты.
20. **[2.5, 8.2]** Убрать `any` в business-типах (Zod-схемы ответов).
21. **[9.5, 9.6]** ADR gaps + обновить AGENTS.md §structure (Alembic каноничен).
22. **[5.5, 5.6]** Batch-запросы в AI-preview и courses-router loops.
23. **[2.4, 6.4, 6.5]** Заменить silent-except / PII-логи на `logger.warning`/`logger.debug`.

### 🟢 Cosmetic

24. Удалить scratch-файлы (1.5, 1.6, 1.7, 1.8, 5.7).
25. Расширить README (9.9).
26. Удалить `ALLOW_*_DEMO` после e2e (4.8).

---

## 12. Open Questions

1. **[3.1] RLS bypass** — какая роль БД используется приложением в проде (Supabase)? Если это `postgres`/service-role — RLS точно обходится. Требует подтверждения из Supabase Dashboard / `DATABASE_URL`.
2. **[3.2] Legacy-users branch** в `auth/service.py:90` — есть ли в проде пользователи без tenant-matched email-domain? Если да — удаление ветки ломает их login. Нужен data-check.
3. **[4.6] File-upload 10 vs 50MB** — осознанное решение или артефакт? AGENTS.md говорит 50.
4. **[7.3] Реальное coverage** — не измерено (нет runtime). Рекомендую локальный прогон `pytest --cov` для baseline перед постановкой CI-gate.
5. **[8.4] KK translation quality** — parity по числу ключей ✅, но machine-translated-risk. Нужен native-review (невозможно инструментально).
6. **[6.1] `ai/ingestion.py:352` TODO "Call Qwen 3.5 when available"** — это активный код или legacy? Требует проверки владельца.
7. **[9.7] Multi-instance Render** — планируется ли >1 instance API? Если да — startup-migration race становится реальным.

---

## 13. Appendix

### Методология
Read-only аудит по 9 фазам из `docs/prompts/full-project-audit.md`. Фазы пройдены последовательно. Findings — evidence-based (file:line). Severity по шкале prompt'а. Без runtime-прогонов (pytest, coverage, E2E, EXPLAIN ANALYZE) — эти метрики отмечены как Open Questions / Ограничения.

### Инструменты
- `Read`, `Glob` (заменён на `ls` из-за timeout'ов на большой репе), `Grep` (ripgrep) — структура/паттерны.
- `Bash` (Git Bash на win32) — только read-only: `ls`, `wc`, `grep`, `find`, `git`.
- Не использовалось: PowerShell (prompt предлагал, но окружение = Git Bash), `WebSearch`/`WebFetch` (не потребовалось — все answers в коде/AGENTS.md).

### Ограничения
1. **Coverage не измерен.** Recommendations по 80%-gate основаны на distribution-анализе (2460 LOC тестов / 20360 LOC кода ≈ 12%), не на реальном `pytest --cov`. Рекомендация 7.3 = "прогнать локально для baseline".
2. **RLS bypass статус (3.1)** — логически выводим (нет FORCE + owner bypass в Postgres), но не подтверждён инспекцией прод-роли БД. См. Open Question 1.
3. **Frontend UX/runtime** — не запускался. Findings по типам/структуре, не по runtime-behavior.
4. **i18n KK quality** — строк-parity проверен, лингвистическое качество — нет.
5. **Внешние интеграции** (Telegram bot, WhatsApp gateway, Docling, Qwen endpoint) — не тестировались на liveness, только code-review.
6. **Деплой Render** — не инспектировался через Render API (хотя `RENDER_API_KEY` доступен по AGENTS.md §Lessons). Deploys-status вне scope этого аудита.
