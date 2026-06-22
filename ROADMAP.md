# Kamilya LMS — План доработки

> На основе аудита кодовой базы от 22 июня 2026

---

## Фаза 1: Критичные баги (1 спринт)

### 1.1 Авторизация сломана
**Проблема:** `require_admin` проверяет `user.role`, но модель `User` не имеет поля `role` — есть отдельная таблица `user_roles`. Авторизация не работает.

**Фикс:**
- `core/auth.py` — `get_current_user` должен подтягивать роли из `user_roles`
- `require_role` — проверять по списку ролей из БД, не из JWT claims
- `require_admin` —统一 через `require_role("admin")`
- Telegram login — брать роль из БД, не хардкодить `"student"`

### 1.2 JWT HS256 с dev-секретом
**Проблема:** `config.py` содержит `"dev-secret-dont-use-in-production"`. Любой может подделать токен.

**Фикс:**
- `JWT_SECRET` только из env vars, нет дефолта в коде
- При отсутствии — падать при старте, не использовать dev-secret
- Добавить `jti`, `iat`, `nbf` в claims для возможности отзыва

### 1.3 auth_sessions in-memory
**Проблема:** Сессии хранятся в `dict` — сброс при рестарте, нет горизонтального масштабирования.

**Фикс:**
- Перенести в Redis (Upstash) с TTL
- Или в таблицу `user_sessions` (уже есть в БД)
- При logout — удалять сессию, не обнулять refresh_token

### 1.4 CSP unsafe-inline + unsafe-eval
**Проблема:** `script-src 'self' 'unsafe-inline' 'unsafe-eval'` = XSS-векторы открыты.

**Фикс:**
- Убрать `unsafe-eval`
- `unsafe-inline` заменить на nonce-based CSP
- Генерировать nonce на request, передавать в шаблоны

---

## Фаза 2: Безопасность (2 спринта)

### 2.1 RLS в Postgres
**Проблема:** Изоляция только на ORM-уровне. Прямой SQL = утечка кросс-тенант.

**Фикс:**
- `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` на все таблицы с `tenant_id`
- Policy: `tenant_id = current_setting('app.current_tenant')::uuid`
- При входе — `SET app.current_tenant = '<uuid>'`
- Все raw SQL запросы проходят через RLS автоматически

### 2.2 WebSocket без аутентификации
**Проблема:** `/ai/ws/jobs/{job_id}` принимает любое соединение.

**Фикс:**
- WS handshake проверяет JWT из query params или headers
- Проверять что user имеет доступ к job (через tenant_id)
- Добавить heartbeat + timeout

### 2.3 Rate limiting
**Проблема:** Fail-open при падении Redis, brute-force на `/auth/check-code`.

**Фикс:**
- Fail-closed: если Redis недоступен — блокировать запросы (или лимит в памяти)
- Отдельный лимит на `/auth/check-code`: 5/min на IP+code
- Rate limit key = IP + user_id (если авторизован)

### 2.4 File upload без MIME проверки
**Проблема:** Нет проверки magic bytes, content-type от клиента.

**Фикс:**
- Проверка magic bytes (PDF: `%PDF`, DOCX: PKZIP signature)
- ClamAV для антивирусной проверки (опционально)
- Ограничение по расширению + MIME

### 2.5 Прочее
- JWT в httpOnly cookie вместо localStorage
- `blacklist_refresh_token` — удалять сессию, не обнулять
- Валидация сложности пароля при register
- CORS: `allow_methods=["GET","POST","PUT","DELETE"]`, `allow_headers=["Authorization","Content-Type"]`

---

## Фаза 3: AI Pipeline (2 спринта)

### 3.1 Рабочие эмбеддинги
**Проблема:** Все эмбеддинги `[0.0]*1024` — RAG не работает.

**Фикс:**
- Подключить реальные эмбеддинги Qwen (`10.66.66.7:8001`)
- Если Qwen недоступен — BM25 fallback (Rank_bm25, pip install)
- Ingester: реальные embeddings → ChromaDB
- Writer: реальный retrieval + rerank

### 3.2 Reviewer
**Проблема:** Placeholder на regex-проверках. ТЗ требует LLM-as-judge.

**Фикс:**
- Qwen как judge: score 1-5 по критериям (структура, глубина, практика)
- Retry при score < 0.7 (макс. 2 попытки)
- Fallback: если Qwen недоступен — пропускать review с предупреждением

### 3.3 Удалить in-memory dict
**Проблема:** `ai/service.py` с `_jobs: Dict` параллельно с `ai/job_service.py` в БД.

**Фикс:**
- Удалить `ai/service.py` и `_jobs`
- Все операции через `job_service.py` (Postgres)

### 3.4 WebSocket polling → Redis pub/sub
**Проблема:** WS-хендлер опрашивает БД каждые 2 сек.

**Фикс:**
- Celery task публикует progress в Redis channel `ai:job:{job_id}`
- WS-хендлер подписывается на channel
- Backpressure: max 100 concurrent WS connections

---

## Фаза 4: Качество кода (1 спринт)

### 4.1 Lifespan вместо on_event
**Проблема:** `@app.on_event("startup")` deprecated, race condition при масштабировании.

**Фикс:**
- `async with lifespan(app):` в `main.py`
- Миграции в отдельном CLI command, не в startup
- `alembic upgrade head` как Render startup command

### 4.2 Убрать sys.path хаки
**Проблема:** `sys.path.insert(0, ...)` в `__init__.py`.

**Фикс:**
- `pyproject.toml` с правильными package configs
- Или `pip install -e .` в monorepo

### 4.3 Next.config.js
**Проблема:** `ignoreBuildErrors: true` — типы не проверяются.

**Фикс:**
- Убрать `ignoreBuildErrors`
- Убрать `ignoreDuringBuilds`
- Пофиксить все TS ошибки

### 4.4 Audit log автоматический
**Проблема:** Модель есть, но нигде не вызывается автоматически.

**Фикс:**
- FastAPI middleware или event hooks
- Логировать: login, logout, create/update/delete course, upload document, assign position
- Писать в `audit_logs` через service layer

---

## Фаза 5: Frontend (2 спринта)

### 5.1 Подключить lucide-react
**Проблема:** Inline SVG в каждом файле, дублирование.

**Фикс:**
- `npm install lucide-react`
- Заменить inline SVG на `<IconName size={20} />`
- Tree-shaking автоматически

### 5.2 Заменить confirm/alert
**Проблема:** Нативные диалоги в admin.

**Фикс:**
- Использовать существующий `Modal` компонент для confirm
- Toast-уведомления вместо alert

### 5.3 Debounce на поиск
**Проблема:** Каждый keystroke = запрос к API.

**Фикс:**
- `useDebouncedValue` хук (300ms)
- Или `setTimeout` в useEffect

### 5.4 Skeleton loaders
**Проблема:** Только спиннеры, нет skeleton.

**Фикс:**
- Добавить skeleton-компоненты для tables, cards, stats
- Показывать до получения данных

### 5.5 Error pages
**Проблема:** Нет 404/500 страниц.

**Фикс:**
- `app/not-found.tsx`
- `app/error.tsx`
- `app/global-error.tsx`

### 5.6 WCAG enforcement
**Проблема:** WCAG.md — памятка, нет enforcement.

**Фикс:**
- axe-core в dev mode (autofix)
- `aria-label` на кнопках без текста
- Исправить вложенные `<a>` в courses
- `focus:ring-*` на всех интерактивных элементах

---

## Фаза 6: Тесты (1 спринт)

### 6.1 Backend тесты
- Unit tests для service layer (покрытие ≥ 80%)
- Integration tests для критических endpoints
- Auth flow tests (register, login, refresh, logout)
- AI pipeline tests (с моком Qwen)

### 6.2 Frontend тесты
- Vitest для хуков и утилит
- Компонентные тесты для критических форм

### 6.3 CI
- GitHub Actions: lint + typecheck + test на каждом PR
- pytest с coverage report
- ESLint + TypeScript strict

---

## Фаза 7: Инфраструктура (1 спринт)

### 7.1 Мониторинг
- Sentry для error tracking (frontend + backend)
- Server timing headers
- Health check endpoint с DB/Redis ping

### 7.2 Backups
- restic в B2 (2 региона)
- Ежедневный cron job
- Тест восстановления раз в месяц

### 7.3 CSP hardened
- Nonce-based inline scripts
- Report-Only header для тестирования
- Subresource Integrity (SRI) для CDN

---

## Таймлайн

| Фаза | Спринт | Описание |
|------|--------|----------|
| 1 | S1 | Критичные баги (авторизация, JWT, сессии, CSP) |
| 2 | S2-S3 | Безопасность (RLS, WS auth, rate limiting, upload) |
| 3 | S4-S5 | AI pipeline (эмбеддинги, reviewer, Redis pub/sub) |
| 4 | S6 | Качество кода (lifespan, sys.path, TS, audit) |
| 5 | S7-S8 | Frontend (lucide, modal, debounce, skeleton, a11y) |
| 6 | S9 | Тесты (backend, frontend, CI) |
| 7 | S10 | Инфраструктура (monitoring, backups, CSP) |

**Итого: ~10 спринтов (5 месяцев) до GA**

---

*Создано: 22 июня 2026*
*На основе аудита кодовой базы*
