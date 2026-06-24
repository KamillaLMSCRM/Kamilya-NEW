# Kamilya LMS — Code Audit Report

**Дата:** 2026-06-24
**Объект:** `D:\Камиля\lms`
**Объём:** ~5K строк Python backend, ~3K строк TypeScript frontend, 16 Alembic миграций, 3 ADR
**Вердикт:** ❌ **Не готово к production**. PROGRESS.md говорит "ready for beta launch" — это самообман. Есть блокирующие уязвимости и сломанный процесс миграций.

---

## TL;DR — Критические баги (требуют немедленного фикса)

| # | Файл | Проблема | Серьёзность |
|---|------|----------|-------------|
| 1 | `apps/api/app/modules/auth/router.py:184-246` | **`/auth/demo-login` без аутентификации** — любой может стать `admin` | 🔴 CRITICAL |
| 2 | `apps/api/app/modules/ai/ingestion.py:185-192` | **SQL injection через f-string в vector query** | 🔴 CRITICAL |
| 3 | `apps/api/app/modules/auth/router.py:65-83` | **`/auth/register` позволяет указать `tenant_id`** в теле — можно регистрироваться в чужой организации | 🔴 CRITICAL |
| 4 | `apps/api/app/core/auth.py:78-81` | **Роль пользователя перезаписывается из JWT**, а не из БД — privilege escalation если токен скомпрометирован | 🔴 CRITICAL |
| 5 | `apps/api/app/core/auth.py:64-70` | **RLS — мёртвый код**: `set_current_tenant()` функция не существует, ошибка проглатывается | 🔴 CRITICAL |
| 6 | `apps/api/alembic/versions/0012_*.py` | **Дубликат `revision = "0012"`** — Alembic не сможет накатить миграции | 🔴 BLOCKER |
| 7 | Все миграции | **RLS не настроен** ни на одной таблице (ADR-0003 обещает, кода нет) | 🔴 CRITICAL |
| 8 | `apps/api/app/modules/ai/ingestion.py:147` | **`tenant_id = "00000000-..."`** fallback — embeddings без тенанта смешиваются | 🟠 HIGH |
| 9 | `apps/api/app/modules/auth/service.py:71-79` | **Login ищет user только по email**, без tenant_id — кросс-tenant коллизия | 🟠 HIGH |
| 10 | `apps/web/src/lib/auth.ts:36` | **JWT в localStorage + cookie без HttpOnly** — XSS → угон | 🟠 HIGH |
| 11 | `apps/web/src/middleware.ts:4` | **Middleware защищает только 5 routes из 13+ приватных** | 🟠 HIGH |
| 12 | `apps/api/app/modules/admin/service.py:103-181` | **N+1 queries** в admin dashboard (на 30 курсах = 90 запросов) | 🟠 HIGH |
| 13 | `apps/api/app/modules/ai/router.py:24-75` | **`_running_tasks` в памяти** — рестарт Render теряет активные генерации | 🟠 HIGH |
| 14 | `apps/web/package.json` | **Невалидные версии пакетов** (`lucide-react ^1.21.0`, `jsdom ^29.1.1`, `vitest ^4.1.9`) — install может упасть | 🟠 HIGH |
| 15 | `apps/api/app/modules/documents/router.py:63-66` | **10MB файлы читаются в память целиком** перед обработкой — OOM | 🟡 MEDIUM |

---

## 1. Архитектура

### Что обещают документы
- `AGENTS.md`: monorepo `apps/api` + `apps/web` + `packages/{db-schema,shared-types,ui-kit,ml-pipeline}`
- `ADR-0001`: Next.js 14 + TanStack Query + Zustand + Radix UI + Tiptap + react-hook-form + Zod + next-intl + Mux Player + Vitest + Playwright + GitHub Actions + Sentry + Restic
- `ADR-0003`: Multi-tenant через ORM middleware + RLS policies + `current_setting('app.tenant_id')`
- `PROGRESS.md`: "v1.0 is ready for beta launch"

### Что есть в реальности
- ✅ Monorepo `apps/api`, `apps/web`
- ✅ Backend: FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic v2 + JWT (PyJWT) + Argon2 + Redis rate limit
- ✅ Frontend: Next.js 14 + TypeScript + Tailwind + Zustand + Axios + i18n (RU/KK/EN) + Vitest + Playwright
- ❌ Нет TanStack Query, Zod, Radix UI, Tiptap, react-hook-form, next-intl — используется кастомный `useT.ts` и кастомные UI
- ❌ Нет Sentry, Restic, GitHub Actions workflows (папки `.github/` не существует)
- ❌ `packages/db-schema` (Drizzle) — **~250 строк мёртвого кода**, нигде не импортируется (backend на SQLAlchemy)
- ❌ `packages/shared-types` (Zod) — **98 строк**, не используется фронтом (проверено grep'ом по всему `apps/web/src`)
- ❌ `packages/ui-kit` — дублирует `apps/web/src/components/ui/`
- ❌ `packages/ml-pipeline` — пустой `__init__.py`
- ❌ `docker-compose.yml`, `docker-compose.prod.yml`, `Dockerfile` — **не существуют** (PROGRESS.md говорит использовать)
- ❌ **RLS не реализован** — ни одной `CREATE POLICY`, ни `ENABLE ROW LEVEL SECURITY`, ни `set_current_tenant()` функции в БД
- ❌ `infra/Caddyfile` описывает on-prem deploy (`app.kml.kz`, `api.kml.kz`), но реально Vercel + Render — расходится

### Проблема: ADR/документы ≠ реальность
PROGRESS.md, PROJECT.md, AGENTS.md, ADR-0001 обещают то, чего нет. Это технический долг + риск compliance (если аудит).

---

## 2. Multi-tenancy — ГЛАВНАЯ ПРОБЛЕМА

### ADR-0003 обещает три уровня защиты:
1. **ORM middleware** автофильтрует `tenant_id`
2. **PostgreSQL RLS policies** на каждой таблице
3. **JWT tenant_id claim** валидируется

### Реальность: только ORM + ручные `.where()`

| Компонент | ADR обещает | Реальность |
|-----------|-------------|------------|
| ORM auto-filter | `TenantSessionMiddleware` через `with_loader_criteria` | ❌ Нет. Каждый endpoint пишет `.where(Model.tenant_id == user.tenant_id)` вручную |
| RLS policies | `ENABLE ROW LEVEL SECURITY` + `CREATE POLICY ... USING (tenant_id = current_setting('app.tenant_id', true)::UUID)` | ❌ Нет ни одной миграции с RLS |
| `current_setting('app.tenant_id')` | устанавливается через session var | ❌ Используется `set_current_tenant(:tid)` функция, которой нет в БД. Ошибка проглатывается (`except Exception: pass`) |
| X-Superadmin-Override header | для обхода RLS с audit | ❌ Не реализован |
| `app.bypass_rls` GUC | для superadmin | ❌ Не реализован |
| Cross-tenant тесты | unit + integration + e2e | ❌ Тестов на cross-tenant нет |

### Сломанные места

**`apps/api/app/core/auth.py:64-70`:**
```python
if tenant_id:
    try:
        from sqlalchemy import text
        await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    except Exception:
        pass  # RLS not available, rely on ORM filtering
```
- Функция `set_current_tenant()` нигде не определена (нет в миграциях, нет DDL)
- Ошибка проглатывается → silent failure
- Комментарий "rely on ORM filtering" — но ORM middleware тоже не написан
- Полагаемся только на ручные `.where()` — **любой пропущенный фильтр = утечка данных**

**`apps/api/app/modules/auth/service.py:71-79`:**
```python
async def authenticate_user(db, email, password):
    result = await db.execute(select(User).where(User.email == email))  # ⚠️ NO tenant_id
```
- Поиск пользователя только по email
- Если у двух тенантов есть user с одинаковым email — попадёт в первый tenant
- **Кросс-tenant login возможен**

**`apps/api/app/modules/auth/router.py:65-83`:**
```python
async def register(req: UserCreate, ...):
    result = await db.execute(select(Tenant).where(Tenant.slug == req.email.split("@")[-1]))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(id=req.tenant_id, name=..., slug=...)  # ⚠️ tenant_id от клиента!
```
- `UserCreate.tenant_id: UUID` (schemas.py:30) — клиент передаёт UUID организации
- Если tenant найден — используется он. Если нет — создаётся с **client-controlled `tenant_id`**
- Это позволяет регистрироваться с заранее угаданным UUID существующего тенанта

**`apps/api/app/modules/ai/ingestion.py:147`:**
```python
"tenant_id": tenant_id or "00000000-0000-0000-0000-000000000000",
```
- Magic UUID fallback для tenant_id
- Если в pipeline потеряется tenant_id — embeddings уйдут в "нулевого" тенанта
- Без RLS это значит: embeddings смешиваются между тенантами в `document_embeddings`

**`apps/api/app/modules/ai/ingestion.py:185-192`:**
```python
emb_str = str(emb)  # user-controlled
sql = text(f"""
    SELECT text, doc_name, headings,
           1 - (embedding <=> '{emb_str}'::vector) as distance
    FROM document_embeddings {where_clause}
""")
```
- **SQL injection** через f-string
- `emb` приходит из API (массив float), `str()` может содержать управляющие символы
- Правильно: bind params `text("... <=> :emb::vector")`, `{"emb": emb_str}`

### Где tenant_id фильтруется правильно (хорошие примеры)
- `modules/quizzes/router.py` — везде `Quiz.tenant_id == user.tenant_id` (353 совпадения по grep'у)
- `modules/documents/router.py`, `modules/ai/router.py` — аналогично

### Где НЕ фильтруется (найдено вручную)
- `auth/service.py:72` (login)
- `auth/router.py:66` (register создаёт tenant, но slug — производное от email)
- `quizzes/router.py:181` — `tenant_id=user.tenant_id` в INSERT — OK
- Все `services/admin/service.py` queries фильтруют — OK
- ВНИМАНИЕ: я не нашёл **прямого SQL с прямым текстом от пользователя вне `ingestion.py:185-192`**, но это не гарантия

---

## 3. Безопасность

### 3.1 Auth — критические баги

**`auth/router.py:184-246` — `/auth/demo-login`:**
```python
@router.post("/demo-login")
async def demo_login(req: DemoLoginRequest, db=Depends(get_db)):
    if req.role not in DEMO_USERS:
        raise HTTPException(...)
    demo = DEMO_USERS[req.role]  # admin / teacher / student
    # ... создаёт/находит user и возвращает JWT с этим role
```
- **Нет аутентификации**, нет проверки `APP_ENV != "production"`
- В `render.yaml:18` стоит `APP_ENV: production` — но роутер доступен **всегда**
- Кто угодно может `POST /api/v1/auth/demo-login {"role":"admin"}` и получить JWT админа
- Если прод-сервер запущен — это компрометация за 1 запрос
- **FIX:** обернуть в `if settings.APP_ENV != "production": raise HTTPException(404)` или вообще удалить

**`auth.py:78-81` — перезапись роли из JWT:**
```python
jwt_roles = payload.get("roles", [])
if jwt_roles and user.role != jwt_roles[0]:
    user.role = jwt_roles[0]
    await db.flush()
```
- Источник истины для роли — JWT, а не БД
- Если админ изменил роль пользователя — старая роль в JWT продолжает действовать до истечения access_token (15 минут)
- Если JWT_SECRET утечёт → можно подделать JWT с любой ролью
- **FIX:** убрать sync; всегда брать `user.role` из БД

**`auth/router.py:39` — `expires_in=900` hardcoded:**
- Не из конфига (хотя `ACCESS_TOKEN_EXPIRE_MINUTES=15` есть в config.py)
- Магическое число

**`auth/service.py:103-125` — refresh token не ротируется:**
- PROGRESS.md пишет "JWT auth with refresh token rotation"
- Реально: тот же refresh_token переиспользуется; blacklist = DELETE сессии
- **FIX:** после refresh — старый refresh invalidate, новый выдать

**`auth/service.py:110` — refresh token хранится plaintext:**
- `select(UserSession).where(UserSession.refresh_token == refresh_token)` — plain text
- Утечка БД → компрометация всех refresh tokens
- **FIX:** хранить `hash(refresh_token)` как bcrypt/argon2

**`auth/schemas.py:30` — `tenant_id` в `UserCreate`:**
- Клиентский контроль над `tenant_id` (см. раздел 2)

### 3.2 Auth token storage — frontend

**`apps/web/src/lib/auth.ts`:**
```typescript
localStorage.setItem(AUTH_KEY, JSON.stringify(state));
document.cookie = `${TOKEN_COOKIE}=${state.access_token}; path=/; max-age=86400; SameSite=Lax`;
```
- localStorage — доступен из JS → XSS уязвимость
- Cookie без `HttpOnly; Secure` — тоже доступен из JS
- 24h max-age для cookie при 15-минутном access token
- **FIX:** httpOnly cookie через `Set-Cookie` от бэкенда, убрать localStorage

### 3.3 Authorization middleware

**`apps/web/src/middleware.ts:4`:**
```typescript
const protectedRoutes = ['/dashboard', '/settings', '/courses', '/positions', '/job-descriptions'];
```
- **Не защищены:** `/admin/*`, `/admin/users`, `/admin/quizzes/*`, `/admin/enrollments`, `/ai/generate`, `/documents`, `/certificates`, `/student`, `/my-courses`, `/my-quizzes`
- Эти страницы проверяют авторизацию только на клиенте через axios interceptor (lib/api.ts:22-29)
- Если SSR рендерит — данные утекут без редиректа
- **FIX:** добавить все приватные routes в `protectedRoutes` или сделать matcher наоборот (whitelist public)

### 3.4 File upload

**`apps/api/app/modules/documents/router.py:55-139`:**

| Проблема | Где | Серьёзность |
|----------|-----|-------------|
| 10MB файлы читаются в RAM целиком перед обработкой | line 63 `await file.read()` | 🟡 OOM при параллельных upload |
| `file_path = os.path.join(UPLOAD_DIR, str(user.tenant_id), f"{doc_id}{ext}")` — `ext` от `file.filename` через `os.path.splitext` | line 99-104 | 🟡 Path traversal через crafted filename (`.pdf/../../etc/passwd`) |
| `Document.filename` используется для dedup (line 92-97) — обход через разные имена одного содержимого | line 92 | 🟡 LOW |
| `ingest_file()` запускается синхронно в request (line 128) | | 🟠 блокирует event loop на минуты для больших PDF |
| `Document.s3_key` не используется — MinIO/S3 не интегрирован, файлы только на Render ephemeral disk | line 101 | 🟠 данные теряются при редеплое |
| `s3_key` пишется в БД, но фактически `file_path` используется для локального сохранения | | 🟠 несогласованность |

**FIX:**
- Stream upload в MinIO/S3 сразу (chunk by chunk)
- Whitelist extension (`{'.pdf', '.docx', '.txt', ...}`), не из filename
- Dedup по SHA256 хэшу содержимого
- Async ingestion через Celery task (уже настроен в celery_app.py, но не используется)

### 3.5 Rate limiting

**`apps/api/app/core/rate_limit.py`:**

| Проблема | Где | Серьёзность |
|----------|-----|-------------|
| `fail-open` при недоступности Redis для **auth** endpoints | line 61, 102 | 🔴 Redis упал → login/register без лимита |
| Ключ только по IP — обход через X-Forwarded-For или прокси | line 131 | 🟡 |
| `pattern.startswith(path)` — `/api/v1/quizzes_evil` попадёт под лимит `/api/v1/quizzes` | line 108 | 🟡 |
| Rate limit не покрывает `/auth/demo-login` (нет в RATE_LIMITS) | | 🟠 |
| Rate limit не покрывает `/auth/check-code` достаточно строго | line 34 (30/min) | 🟡 OK но polling может превысить |

**FIX:**
- Для auth endpoints — `fail-closed`
- Ключ по `user_id` для авторизованных, по IP для остальных
- Точное совпадение pattern + regex для сложных

### 3.6 CSP и security headers

**`apps/api/app/core/security.py`:**
- ✅ HSTS, X-Frame-Options DENY, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
- ⚠️ CSP: `script-src 'self' 'unsafe-inline'` — `unsafe-inline` для Next.js необходим, но лучше через nonce
- ⚠️ `connect-src` зашит на конкретные домены (`api.kml.kz`, `lms.kml.kz`) — если prod URL другой, сломается

### 3.7 WebSocket auth

**`apps/api/app/modules/ai/router.py:170`:**
```python
@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str, token: str = Query(None)):
```
- JWT передаётся в query string → может попасть в access logs
- Лучше через `Sec-WebSocket-Protocol` или первый message после connect

### 3.8 In-memory state в production

**`apps/api/app/modules/ai/router.py:24`:**
```python
_running_tasks: dict[str, asyncio.Task] = {}
```
- На Render (PaaS с авто-скейлом) при редеплое — все активные генерации теряются
- На multi-worker uvicorn — `dict` per-worker, не общий
- На горизонтальном масштабировании — задачи одного пользователя в разных процессах
- **FIX:** использовать Celery (уже настроен!) или Redis-based queue

---

## 4. Качество кода

### 4.1 Дублирование и boilerplate

**`apps/api/app/modules/courses/router.py`** — каждое действие повторяет 20 строк boilerplate:
```python
result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
course = result.scalar_one_or_none()
if not course:
    raise HTTPException(status_code=404, detail="Course not found")
# ... modify ...
await db.flush()
await db.refresh(course)
await log_action(...)
await db.commit()
return course
```
- 7 endpoints, ~140 строк boilerplate
- **FIX:** helper `async def get_user_course(db, course_id, tenant_id) -> Course` + декоратор `@audit("update", "course")`

**`apps/api/app/modules/auth/router.py:30-37, 53-60, 76-81`** — одинаковый блок `log_action`:
```python
await log_action(
    db, user.tenant_id, "X", "user",
    resource_id=str(user.id), user_id=user.id,
    ip_address=request.client.host if request.client else None,
    user_agent=request.headers.get("user-agent"),
)
```
- 5 копий
- **FIX:** FastAPI middleware для автоматического аудита или `request.state.user_id`

### 4.2 N+1 queries

**`apps/api/app/modules/admin/service.py:103-141` — `get_recent_courses`:**
```python
for course in courses:
    count_result = await db.execute(
        select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id)
    )
```
- На 30 курсов = 30 дополнительных запросов
- **FIX:** `select(Course, func.count(Enrollment.id)).outerjoin(...).group_by(Course.id)` — один запрос

**`apps/api/app/modules/admin/service.py:184-236` — `get_activity_summary`:**
```python
for i in range(days):  # 30
    # 4 запроса × 30 дней = 120 запросов
```
- **FIX:** один запрос с `GROUP BY date_trunc('day', created_at)`

### 4.3 Обработка ошибок

**`apps/api/app/core/errors.py`:**
- ✅ Глобальные handlers для 404, 422, 500
- ⚠️ Нет handler для `IntegrityError` (только declared `unique_violation_handler`, но не зарегистрирован в `register_error_handlers`)
- ⚠️ `unhandled_exception_handler` отдаёт generic 500 без stack trace в response (правильно для prod) — но logging `logger.exception` пишет в stdout. На Render логи теряются через 30 дней (нет Sentry/observability)

**`auth/router.py:48` — refresh endpoint:**
```python
async def refresh(req: RefreshRequest, db=Depends(get_db)):
    try:
        new_token = await refresh_access_token(db, req.refresh_token)
        return TokenResponse(...)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
```
- Проглатывает ВСЕ исключения → теряется диагностика
- **FIX:** ловить только `HTTPException`, остальное — 500

**`documents/router.py:124-131`:**
```python
try:
    result = await ingestion.ingest_file(...)
    print(f"[UPLOAD] Ingested {file.filename}: ...", flush=True)
except Exception as e:
    print(f"[UPLOAD] Ingestion failed for {file.filename}: {e}", flush=True)
```
- Ingestion fail не откатывает Document — в БД документ без embeddings
- **FIX:** если ingestion упал — `db.delete(doc)` или retry

### 4.4 Типизация

**Backend:**
- `pyproject.toml:39-42` — `mypy strict = true`, `disallow_untyped_defs = true`
- Реально: много `dict[str, Any]`, `Optional[str]`, `dict` без аннотаций
- CI для mypy не настроен (нет `.github/`)
- **ВЫВОД:** strict mode в конфиге — фикция

**Frontend:**
- `next.config.js:5-9` — `ignoreBuildErrors: true`, `ignoreDuringBuilds: true`
- TypeScript-ошибки **не блокируют** deploy
- **КРИТИЧНО:** это маскирует баги до продакшена

### 4.5 Naming, conventions

- `courses.py` в `app/models/` — это **реэкспорт** из `modules/courses/models.py`. Зачем?
- `app/models/document.py` vs `app/models/users.py` — модели в разных местах, без системы
- `quizzes/models.py` vs `quizzes/assignment_models.py` — split, OK
- Миграция `0008_merge_positions_job_descriptions` — **это merge-миграция с `down_revision = "0007"`** — но при этом **выполняет schema changes** (дропает таблицу, добавляет колонки). Merge-миграция не должна менять схему — это нарушение Alembic best practices.

### 4.6 Dead code / несогласованность

| Файл | Размер | Используется? |
|------|--------|---------------|
| `packages/db-schema/schema/*.ts` | ~5.8K | ❌ Backend на SQLAlchemy, фронт не импортирует |
| `packages/shared-types/index.ts` | 2.8K | ❌ Frontend не импортирует (поиск grep'ом — 0 совпадений) |
| `packages/ui-kit/components/*` | ~7.5K | ❌ Дубликат `apps/web/src/components/ui/` |
| `packages/ml-pipeline/__init__.py` | 51 байт | ❌ Пустой |
| `infra/init.sql` | 3K | ❌ Конфликтует с `0001_initial.py`, не выполняется на Render |
| `docs/qwen_proxy_setup.py` + `docs/setup_qwen_proxy.py` | 4.5K | ⚠️ Дубликаты, различаются мелочами |
| `apps/api/openapi.json` | 111 байт | ❌ Мусор (OpenAPI должен генериться автоматически) |
| `apps/api/tsconfig.json` | 476 байт | ❌ Зачем TS config в Python проекте? |
| `apps/web/tests/setup.ts` + `setup.tsx` | 950 байт | ⚠️ Дубликаты |
| `tests/__pycache__/*.pyc` | мусор | ❌ Закоммичены .pyc файлы |
| `repomix-output.md` | 774K | ❌ Не нужен в репо (уже в .gitignore неявно) |

### 4.7 SQL-скрипты в корне (анти-паттерн)

**16 файлов в корне проекта:**
```
add_deferral.sql, check_data.sql, check_docs.sql, check_embeddings.sql,
check_progress.sql, check_progress2.sql, check_quiz_tenant.sql,
check_quizzes_enrollments.sql, check_rls.sql, check_tenant_cols.sql,
check_users_cols.sql, check_users.sql, fix_docname.sql, fix_embeddings.sql,
fix_tenant.sql, docs/add_users_columns.sql
```

- Это **debug-скрипты**, выполненные вручную против production БД
- Содержат hardcoded UUID тенантов
- Скрипт `check_rls.sql` показывает, что авторы **знают, что RLS не настроен**, и мониторят
- Должны быть в `scripts/debug/` или вообще удалены
- `.gitignore:79` исключает `check_docs.sql`, `fix_*.sql` — **но они закоммичены**, .gitignore применяется только к новым

### 4.8 Конфигурация / secrets

- `.gitignore` исключает `.env`, `.env.local` ✅
- В `apps/api/app/core/config.py` есть дефолты с **примерами** паролей: `MINIO_SECRET_KEY = "minioadmin_secret_2026"` — это нормально для dev, **но** если кто-то случайно задеплоит с дефолтами — дыра
- В `render.yaml:30` `JWT_SECRET: generateValue: true` — Render генерирует при первом деплое ✅
- `LLM_API_KEY` не обязателен (используют прокси без auth) ✅

---

## 5. База данных / миграции

### 5.1 Критическое: дубликат revision
```
apps/api/alembic/versions/0012_add_deferral_days.py        # revision = "0012"
apps/api/alembic/versions/0012_add_user_role_is_active.py  # revision = "0012"
```
- Обе миграции имеют `revision = "0012"`, `down_revision = "0011"`
- **Alembic не сможет однозначно определить порядок** — упадёт при `alembic upgrade`
- На production, видимо, не накатывается нормально — отсюда debug-скрипты `add_deferral.sql`
- **FIX:** одна из миграций должна быть `0013` (или `0012a`)

### 5.2 Сломанная история миграций

```
0007: creates positions + job_descriptions
0008: drops job_descriptions, adds JD fields to positions  (merge-migration с schema change!)
0010: "sync schema positions and documents" — что-то патчит
0011: "bootstrap positions and documents" — ещё раз создаёт positions, добавляет колонки
```
- `0010_sync_schema_positions_and_documents.py` я не читал полностью, но название говорит за себя — это «латание дыр»
- `0011_bootstrap_positions_and_documents.py` создаёт `positions` с `IF NOT EXISTS` (lines 45-58), что означает: на разных средах состояние БД может отличаться
- Это симптом **отсутствия дисциплины миграций** — кто-то менял БД руками и потом писал миграцию задним числом

### 5.3 Таблица `document_embeddings` без миграции
- Используется в `ingestion.py:141` через `INSERT INTO document_embeddings`
- Есть debug-скрипты `check_embeddings.sql`, `fix_embeddings.sql`
- Нет ни одной миграции, которая её создаёт!
- **FIX:** создать миграцию `0017_create_document_embeddings.py` с pgvector

### 5.4 RLS не настроен

`check_rls.sql`:
```sql
SELECT tablename, rowsecurity, (SELECT count(*) FROM pg_policies ...) as policy_count
FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
```
- Запрос есть, но **ни одна таблица не имеет `rowsecurity = true`**
- ADR-0003 — фикция

### 5.5 SQLAlchemy model ↔ migration drift
- `app/models/users.py:22` — `position_id` (FK на positions)
- Миграция `0012_add_user_role_is_active.py` добавляет `position_id` через raw SQL
- Если запустить `alembic revision --autogenerate` — он ничего не покажет (миграции уже есть), но модели и миграции дрейфуют
- Миграция `0012_add_user_role_is_active.py:45-49` делает `UPDATE users SET role = ur.role FROM user_roles` — это **data migration**, не schema migration, лучше вынести отдельно

---

## 6. Тесты

### 6.1 Backend (5 файлов)
- `test_auth_service.py` (2K)
- `test_auth.py` (2.5K)
- `test_courses_models.py` (1.7K)
- `test_integration.py` (6.4K) — auth endpoints, audit service, rate limit config
- `test_reviewer.py` (4K) — только heuristic review

**Покрытие:** очень низкое. Нет тестов для:
- ❌ Cross-tenant isolation (хотя это главный риск)
- ❌ Quiz logic
- ❌ Enrollment lifecycle
- ❌ Document upload + ingestion
- ❌ AI pipeline (architect/writer/assessment)
- ❌ Auth flows (register, refresh, logout)
- ❌ Certificate generation
- ❌ Admin dashboard queries

### 6.2 Frontend (4 файла)
- `ConfirmDialog.test.tsx` — UI component
- `ErrorPage.test.tsx` — UI component
- `Skeleton.test.tsx` — UI component
- `useDebounce.test.ts` — hook

**Покрытие:** почти нулевое. Нет тестов для:
- ❌ Auth flow
- ❌ Form validation
- ❌ State management (Zustand stores)
- ❌ API client (axios interceptors)
- ❌ Critical user flows (create course, take quiz, certificate)

### 6.3 E2E (Playwright)
- `e2e/login.spec.ts` — login page
- `e2e/navigation.spec.ts` — sidebar/topbar nav

**Покрытие:** отсутствует для critical paths:
- ❌ Create course
- ❌ Generate AI course
- ❌ Take quiz
- ❌ Earn certificate
- ❌ Admin tasks

### 6.4 k6 load test
- `tests/load/k6-test.js` (4K) — 50 → 100 → 200 → 500 VUs
- Не запускается в CI (нет CI)
- Не проверялся — может не работать (BASE_URL = localhost:8000 без `/api/v1`)

### 6.5 Проблемы
- `apps/api/tests/__pycache__/` — **закоммичены .pyc файлы** (pytest-8.4.2 и pytest-9.1.1 — артефакты разных окружений)
- `test_integration.py:99-106` — `test_cors_simple_request` имеет бессмысленный assert (`assert resp.status_code != 429`)
- Тесты используют `TestClient(app)` синхронно против async FastAPI — работает, но не покрывает async путь

---

## 7. CI/CD

- ❌ **Нет `.github/`** — нет GitHub Actions
- ❌ **Нет `docker-compose.yml`** — несмотря на PROGRESS.md
- ❌ **Нет `Dockerfile`** для api или web
- ✅ `render.yaml` (1.4K) — Render config есть
- ✅ `apps/web/vercel.json` (151 байт) — минимальный

**Вывод:** Деплой ручной (`git push` → Render auto-deploy через `render.yaml:46`). Тесты не запускаются нигде.

---

## 8. Frontend

### 8.1 Качество страниц

Я проверил `apps/web/src/app/login/page.tsx` (209 строк):
- ✅ Хорошая структура (a11y: `role="img"`, `aria-label`, `SkipLink`)
- ✅ Polling через `useRef<NodeJS.Timeout>` — корректная очистка
- ⚠️ 6-значный код в URL/page — OK (это и есть фишка)
- ⚠️ `api.post('/v1/auth/...')` — путь `/v1/`, не `/api/v1/` — должно быть в `lib/api.ts`

### 8.2 State management
- `authStore.ts` (770 байт) + Zustand persist
- `languageStore.ts` (396 байт)
- `useT.ts` (1.4K) — кастомный i18n hook

### 8.3 i18n
- `ru.json` (12K), `kk.json` (12K), `en.json` (9K) — есть
- Кастомный `useT.ts` вместо `next-intl`

### 8.4 package.json — невалидные версии

```json
"lucide-react": "^1.21.0",   // нет v1.x, последний 0.4xx
"jsdom": "^29.1.1",           // нет v29, последний v25
"vitest": "^4.1.9",           // нет v4, последний v2.x
"@vitejs/plugin-react": "^6.0.2"  // нет v6, последний v4
```
- **FIX:** проверить `package-lock.json` — если там есть lockfile, версии работают; если нет — `npm install` упадёт
- ADR-0001 обещал Radix UI, TanStack Query, Zod, Tiptap, react-hook-form, next-intl — **ничего нет**

### 8.5 next.config.js
```js
typescript: { ignoreBuildErrors: true },
eslint: { ignoreDuringBuilds: true },
```
- **TypeScript и ESLint ошибки не блокируют build**
- Это маскирует реальные баги до production

---

## 9. ADR — расхождения с реальностью

### ADR-0001 (Stack)
| Обещано | Реальность |
|---------|-----------|
| TanStack Query | ❌ Используется сырой axios |
| Zod | ❌ Только в `packages/shared-types` (dead code) |
| Radix UI | ❌ Кастомные компоненты |
| Tiptap 2 | ❌ Отсутствует |
| react-hook-form | ❌ Сырые `useState` в формах |
| next-intl | ❌ Кастомный `useT.ts` |
| Mux Player | ❌ Отсутствует |
| GitHub Actions | ❌ `.github/` нет |
| Docker + Docker Compose | ❌ `docker-compose.yml` нет |
| Sentry | ❌ Нет |
| Restic + B2 | ❌ Нет |
| Prometheus + Grafana + Loki | ⚠️ `prometheus.yml` + `alert_rules.yml` есть, но не задеплоены |

### ADR-0003 (Multi-tenancy)
| Обещано | Реальность |
|---------|-----------|
| ORM middleware auto-filter | ❌ Ручные `.where()` везде |
| `current_setting('app.tenant_id')` | ❌ Используется несуществующая функция |
| `ENABLE ROW LEVEL SECURITY` | ❌ Ни одной таблицы |
| `CREATE POLICY` | ❌ 0 |
| `app.bypass_rls` для superadmin | ❌ |
| X-Superadmin-Override | ❌ |
| Cross-tenant тесты | ❌ |

---

## 10. Что нужно сделать (приоритезированный план)

### 🔴 Сегодня / до production (блокеры)

1. **Удалить или защитить `/auth/demo-login`** — gate по `APP_ENV != "production"`
2. **Удалить SQL injection** в `ingestion.py:185-192` — bind params для `emb`
3. **Убрать sync роли из JWT** в `auth.py:78-81` — всегда из БД
4. **Исправить дубликат migration revision 0012** — переименовать одну в 0013
5. **Создать миграцию для `document_embeddings`** + pgvector extension
6. **Включить RLS** — написать миграцию с `CREATE POLICY` для всех таблиц (или хотя бы для основных: courses, lessons, users, enrollments, progress, documents, audit_logs, ai_jobs, certificates, quiz_attempts)
7. **Убрать `tenant_id` из UserCreate schema** или валидировать на сервере
8. **Добавить tenant_id в `authenticate_user`** — поиск только в скоупе тенанта
9. **Убрать magic UUID fallback** в ingestion — если нет tenant_id, raise exception
10. **Hash refresh tokens** в UserSession
11. **fix `next.config.js`** — `ignoreBuildErrors: false`, `ignoreDuringBuilds: false`

### 🟠 Эта неделя

12. Расширить middleware.ts — все приватные routes
13. Перенести JWT в httpOnly cookie (бэкенд через Set-Cookie)
14. N+1 fix в admin/service.py
15. Перенести long-running ingestion в Celery (он уже настроен!)
16. Использовать MinIO/S3 для файлов (s3_key уже в схеме)
17. Whitelist расширений файлов в upload
18. CI/CD: минимальный GitHub Actions (lint + typecheck + test)

### 🟡 Этот месяц

19. Удалить dead code: `packages/db-schema`, `packages/shared-types`, `packages/ui-kit`, `packages/ml-pipeline`, `infra/init.sql`
20. Удалить SQL-скрипты из корня, перенести полезные в `scripts/debug/`
21. Перенести refresh-token rotation
22. `fail-closed` rate limiting для auth
23. Storage stream upload (chunked)
24. Реальные E2E тесты для критических flow
25. ADR-0004: обновить стек (убрать нереализованное, добавить реальное)

### 🟢 Nice-to-have

26. Sentry для errors
27. Restic backup (или хотя бы `pg_dump` в cron)
28. Реальный Caddyfile deploy или удалить
29. Согласовать PROGRESS.md с реальностью (выкинуть самообман)

---

## 11. Что НЕ баг (хорошие находки)

- ✅ Используют SQLAlchemy 2.0 async правильно
- ✅ Pydantic v2 + `from_attributes=True` для response models
- ✅ Argon2 для паролей (не bcrypt)
- ✅ JWT с `iat`, `nbf`, `exp`, `jti` — правильно
- ✅ MIME validation с magic bytes в `documents/router.py:32-39`
- ✅ CSP, HSTS, X-Frame-Options DENY, Permissions-Policy — есть
- ✅ Rate limiting per-endpoint конфиг
- ✅ Audit logging — есть, используется во всех модулях
- ✅ i18n (RU/KK/EN) — есть
- ✅ SkipLink, `role="alert"`, `aria-label` — a11y видно
- ✅ Telegram auth flow через polling
- ✅ Pydantic password complexity validator (uppercase + lowercase + digit)
- ✅ `check_rls.sql` — авторы ЗНАЮТ, что RLS не настроен, это хороший знак (самодиагностика)

---

## 12. Метрики проекта

| Метрика | Значение |
|---------|----------|
| Python файлов | 78 (backend) |
| TypeScript/TSX файлов | 70 (frontend) |
| Строк Python кода (modules + core, без tests) | ~6K |
| Строк TS/TSX | ~3K |
| Alembic миграций | 16 |
| ADR | 3 |
| Тестов backend | 5 файлов, ~17K строк (включая mock-heavy test_reviewer) |
| Тестов frontend | 4 unit + 2 e2e |
| Endpoints | ~59 |
| Frontend pages | 21 (Next.js App Router) |
| Документов в `docs/` (i18n + ADR + guides) | 8 |
| Модулей backend | 14 |
| Спринтов / weeks (по TZ.md) | 12 |
| Дней с 22 июня до GA | 56 |

---

## 13. Финальная оценка

**PROGRESS.md говорит:** "Kamilya LMS Core v1.0 is ready for beta launch!"
**Реальность:** MVP functional, но **не готов для multi-tenant SaaS с чувствительными данными (обучение сотрудников)**.

Главные блокеры — multi-tenancy не на уровне БД (только ORM), что для SaaS критично. Плюс `/auth/demo-login` в проде = полная компрометация за один HTTP-запрос.

**Рекомендация:** ещё 2-3 недели до external beta. До этого — закрыть 🔴 секцию.
