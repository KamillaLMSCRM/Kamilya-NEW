# Kamilya LMS — End-to-End Flow: Course Generation to Invitation

Дата: 2026-06-30. Документ описывает **production** flow от создания
курса методологом до приглашения сотрудника. Основан на реальном
коде (`apps/api/app/`) + live smoke через `Invoke-RestMethod` против
`https://kamilya-lms-api.onrender.com/api/v1/`.

Целевая аудитория:
- Разработчик, который впервые прикасается к этому коду
- Askar, который хочет понять какой UI соответствует какому endpoint
- Будущий агент, которому нужно добавить фичу в этот flow

## TL;DR

```text
[1] Методолог: AI generation     -> /api/v1/ai/generate-course (202 + Celery-like)
       Qwen -> DeepSeek failover. Stage progression в /ai/jobs/{id}
[2] Методолог: Review + Publish  -> /api/v1/courses/{id}/review + /publish
[3] Методолог: Staff import       -> /api/v1/admin/staff/import/preview + /commit
       Парсит xlsx/csv. Auto-creates Position + Department.
       Commit диспатчит Celery: positions.apply_course_rules
[4] Методолог: Position→Course    -> /api/v1/positions/{id}/courses (POST/DELETE)
       Sync recompute_enrollments для всех holders.
[5] Методолог: Send invitation    -> /api/v1/users/invitations/bulk
       Копирует invite_url в Slack/Telegram (НЕ email).
[6] Сотрудник: Accept            -> /api/v1/invitations/{token}/accept
       Создаёт пароль. Активирует. Возвращает JWT для auto-login.
[7] Студент: Take course         -> /api/v1/courses/{id}/complete
       Auto-issues certificate.
```

## Auth model (все endpoint'ы)

| Endpoint | Auth | Role |
|---|---|---|
| `POST /auth/generate-code` | public | — |
| `POST /auth/check-code` | public (verified by code) | — |
| `POST /auth/demo-login` | public (demo only) | — |
| `POST /ai/generate-course` | Bearer | any tenant user |
| `GET /ai/jobs/{id}` | Bearer | any tenant user |
| `POST /courses` | Bearer | superadmin, admin, org_admin, teacher |
| `POST /courses/{id}/review` | Bearer | superadmin, admin, org_admin, teacher |
| `POST /courses/{id}/publish` | Bearer | superadmin, admin, org_admin, teacher |
| `POST /courses/{id}/complete` | Bearer | any tenant user (student self-completes) |
| `POST /admin/staff/import/preview` | Bearer | superadmin, admin, org_admin, **methodologist** |
| `POST /admin/staff/import/commit` | Bearer | superadmin, admin, org_admin, **methodologist** |
| `GET /admin/staff/apply-rules/status/{tid}` | Bearer | superadmin, admin, org_admin, methodologist |
| `POST /positions/{id}/courses` | Bearer | methodologist, admin, superadmin |
| `DELETE /positions/{id}/courses/{cid}` | Bearer | methodologist, admin, superadmin |
| `POST /positions/{id}/assign/{uid}` | Bearer | any tenant user (TBD: should be methodologist per ADR §3) |
| `POST /users/invitations/bulk` | Bearer | superadmin, admin, org_admin, **methodologist** |
| `GET /invitations/{token}` | public (token) | — |
| `POST /invitations/{token}/accept` | public (token) | — |

`tenant_id` всегда берётся из JWT (`user.tenant_id`), **никогда** не
из request body. Cross-tenant запросы дают 404, не 403 (см.
`apps/api/app/core/auth.py:218` `require_role` + router-level
`require_tenant_user()` gate).

## Step 1: AI generation (Qwen → DeepSeek)

Файл: `apps/api/app/modules/ai/router.py:43-113`,
`apps/api/app/modules/ai/pipeline.py:225-466`.

```http
POST /api/v1/ai/generate-course
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "course_id": null,           # optional: populate an existing draft
  "documents": ["doc-uuid-1"], # IDs of text-ingested documents (RAG)
  "target_audience": "Junior accountants",
  "num_modules": 3,            # 1-10
  "language": "ru",
  "tone": "professional"
}

→ 202 Accepted
{
  "id": "job-uuid",
  "status": "pending",
  "course_id": null,
  "created_at": "2026-06-30T...",
  "progress": 0,
  "stage": "queued",
  "message": ""
}
```

**Что происходит в бэке (в том же request, `asyncio.create_task`):**
1. `check_ai_generation_quota` — demo plan limit (если tenant demo).
2. `check_and_charge_llm_budget` — atomic UPSERT на
   `tenant_llm_usage`; **429** если перерасходовали $50/tenant/month.
3. `create_ai_job` — INSERT в `ai_jobs` (status=pending, stage=queued).
4. Запускается `_safe_pipeline()` (НЕ Celery — это `asyncio`
   background task, потому что `run_generation_pipeline` использует
   asyncpg). Frontend получает 202 немедленно.

**Pipeline stages (`/ai/jobs/{id}` polling):**

| % | Stage | Что делает | Типичная длительность |
|---|---|---|---|
| 5 | ingestion | Проверяет что у всех `documents` есть pgvector embeddings; падает с `ValueError` если NONE | <1s |
| 10-25 | architect | `run_architect` строит `CourseStructure` (modules + lesson titles) | 5-15s |
| 30-70 | writer | `write_course` генерирует полный content для каждого урока | 30-120s |
| 72 | reviewer | `ReviewerAgent.review_lesson` скорит каждый урок; логирует низкокачественные, продолжает | 5-10s |
| 75-95 | assessment | `generate_course_assessment` строит quizzes | 10-20s |
| 98-100 | saving | INSERT Course (status="draft", ai_generated=true), Module, Lesson, Quiz, Question, QuizChoice | <2s |

**Параллельно (line 418-443):** если задан `state.course_id` и
генератор не имеет существующего enrollment — auto-enroll generator'а.

**WebSocket** `wss://...?token=...` — push обновлений в реальном
времени (`ai/router.py:197-249`). Close codes: 4001 (no token), 4003
(bad token).

### Qwen / DeepSeek failover

Файл: `apps/api/app/modules/ai/llm_client.py:92-124, 393-440`.

```
Chain:
  1. Qwen self-hosted (https://qwen.kml.kz/v1, model cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit)
  2. DeepSeek v4-flash (если есть DEEPSEEK_API_KEY)

Per provider:
  max_retries=2 (3 attempts)
  Retry on: timeout (exp backoff 1→2→4→8s), 429, 502, 503, 504
  Fail-fast: 4xx (other)
  All fail → AllProvidersFailedError

Embeddings chain:
  1. Qwen self-hosted (qwen-embed.kml.kz, Qwen3-Embedding-8B)
  2. Voyage voyage-4-lite (если есть VOYAGE_API_KEY)
```

**Key resolution:**
1. env var (DEEPSEEK_API_KEY / VOYAGE_API_KEY)
2. Active global key в `provider_keys` table
3. Provider skipped

**Известная ловушка (Lesson 1):** `LLMProviderConfig.endpoint`
overridable. `EmbeddingsClient` ДОЛЖЕН override на `/embeddings`;
иначе эмбеддинги уходят на `/chat/completions` и падают.

## Step 2: Review + Publish

Файл: `apps/api/app/modules/courses/router.py`.

```http
POST /api/v1/courses/{id}/review
{
  "review_status": "approved",        # или "needs_changes"
  "comment": "Структура хорошая, но раздел 3 нуждается в доработке"
}

POST /api/v1/courses/{id}/publish
→ обновляет status="published" + published_at=now()
```

**Внимание:** `/publish` **не проверяет** `review_status` — admin
может опубликовать course с `pending` review. Если нужно "publish
только после approved" — добавить check в `router.py:302`.

**Что НЕ происходит:** no LLM call, no fan-out. Только DB
update + audit log.

## Step 3: Staff import (preview + commit)

Файл: `apps/api/app/modules/users/staff_import_router.py:101-222`.

```http
POST /api/v1/admin/staff/import/preview
Content-Type: multipart/form-data
Body: file=<xlsx|csv>

POST /api/v1/admin/staff/import/commit
Content-Type: multipart/form-data
Body: file=<xlsx|csv>
```

**Поддерживаемые форматы:**
- `.csv` — UTF-8-sig / CP1251 / UTF-8 (with replacement)
- `.xlsx` — openpyxl
- `.xls` — **400 "Старый формат .xls не поддерживается"**
- 10 MB max

**Recognized columns (case-insensitive, RU + EN aliases):**

| Canonical | Required | Aliases |
|---|---|---|
| personnel_number | yes | табельный_номер, таб_номер, employee_id, tab_no |
| first_name | yes | имя |
| last_name | yes | фамилия |
| department | yes | отдел, подразделение, цех |
| position | yes | должность |
| email | no | e-mail, почта |
| phone | no | телефон |
| hire_date | no | дата_приема |

### Preview response

```json
{
  "items": [
    {
      "row_number": 2,
      "personnel_number": "EMP001",
      "first_name": "Иван",
      "last_name": "Иванов",
      "department": "Бухгалтерия",
      "position": "Главный бухгалтер",
      "email": "ivanov@example.com",
      "action": "create",          // create | update | skip
      "existing_user_id": null,
      "notes": []
    }
  ],
  "new_positions": ["Бухгалтерия / Главный бухгалтер"],
  "new_departments": ["Бухгалтерия"],
  "summary": {"create": 5, "update": 1, "skip": 0,
              "new_positions": 1, "new_departments": 1,
              "invalid_rows": 0},
  "invalid_rows": [],
  "missing_required_columns": [],
  "total_rows_in_file": 6
}
```

**Errors:**
- 400 "Файл пустой" / parse error
- 413 if > 10 MB
- 400 if missing required columns

### Commit flow (транзакция атомарная)

1. Parse (тот же parser что preview)
2. **422** если есть `invalid_rows` (полный rollback)
3. **400** если нет валидных строк
4. В одной DB транзакции:
   - Auto-create `Position` для новых пар `(department, position)`. `level=""`, `responsibilities=""`, `requirements=""` — методолог заполнит позже через `PUT /v1/positions/{id}`.
   - **Update** существующего user по `personnel_number` (case-insensitive, tenant-scoped). Меняет: first_name, last_name, email, phone, position_id. **НЕ трогает** role/status/is_active/password.
   - **Create** нового user с `role="student"`, `is_active=True`, `password_hash=NULL`, `status="active"`. (Методолог повышает role отдельно через `POST /v1/users/{id}/role`.)
5. COMMIT.

**Auto-enrollment (после commit, async через Celery):**

```python
# staff_import_router.py:200-213
async_result = apply_rules_for_users_task.delay(affected_user_ids)
task_id = async_result.id
```

`apply_rules_for_users_task` — Celery worker на VPS
`173.249.51.164`. Файл: `apps/api/app/modules/positions/tasks.py:25-107`.

### Apply-rules task (Celery)

```python
@celery_app.task(name="positions.apply_course_rules")
def apply_rules_for_users_task(user_ids: list[str]) -> dict:
    """For each user, run apply_rules_for_users(user_id).
    Returns: {users_processed, added, removed, skipped_manual,
              protected_completed, failed_user_ids, errors}
    """
```

Внутри: `recompute_enrollments(user_id)` для каждого user'а.

**Recompute kernel** (`assignment_service.py:58-180`):

1. Load user, derive `tenant_id` from user (never parameter).
2. Collect `expected` set:
   - `PositionCourse` (for user's position) — `required=True` counts
   - `DepartmentCourse` (for position's department)
   - Position wins on collision
3. Split current `Enrollment` rows:
   - `rule_rows` (source ∈ {position, department})
   - `manual_courses` (source='manual')
4. Diff:
   - `to_add`: expected - rule_rows - manual_courses → INSERT
   - `to_remove`: rule_rows - expected (status≠completed) → DELETE
   - `manual_courses`: **никогда не трогаем** (`skipped_manual` counter)
   - Completed rule rows: **никогда не удаляем** (`protected_completed` counter)
5. Apply diff batch.

### Commit response

```json
{
  "created": 5,
  "updated": 1,
  "skipped": 0,
  "positions_created": 1,
  "apply_rules_task_id": "celery-uuid-here",
  "affected_user_count": 6
}
```

### Apply-rules status polling

```http
GET /api/v1/admin/staff/apply-rules/status/{task_id}
```

```json
{
  "task_id": "celery-uuid",
  "state": "SUCCESS",       // PENDING | RECEIVED | STARTED | SUCCESS | FAILURE | RETRY | REVOKED
  "ready": true,
  "successful": true,
  "failed": false,
  "result": {
    "users_processed": 6,
    "added": 18,
    "removed": 0,
    "skipped_manual": 0,
    "protected_completed": 0,
    "failed_user_ids": [],
    "errors": []
  },
  "error": null
}
```

Frontend `<ApplyRulesProgress>` banner поллит каждые 1-2s пока
`state in {PENDING, STARTED, RECEIVED, RETRY}`.

**Известная дыра:** manual trigger `POST /admin/staff/apply-rules`
(для уже импортированных users) **не существует** в коде. Только
через `import/commit`. Это отдельный epic.

## Step 4: Position → Course binding (sync)

Файл: `apps/api/app/modules/positions/router.py:333-459`.

```http
POST /api/v1/positions/{position_id}/courses
{
  "course_id": "uuid",
  "required": true     // default true; counts toward ready_percent
}

DELETE /api/v1/positions/{position_id}/courses/{course_id}
```

**Side effects (sync, в HTTP request thread):**

1. Idempotent insert (если binding уже есть — mutate `required` flag).
2. `recompute_position_holders(db, position_id, user.tenant_id)`
   (`batch_service.py:66-87`) — для каждого User с этой position:
   `recompute_enrollments(user_id)` (см. Step 3).
3. Возвращает `PositionResponse` с `re_enrolled = batch.added`.

**Errors:**
- 404 если position не существует или cross-tenant.
- 500 если cross-tenant INSERT пытается нарушить unique constraint.

**Сравнение с Step 3 (apply-rules через Celery):**
- Step 3: async, для N user'ов сразу (после import).
- Step 4: sync, для всех holders позиции. На большой позиции
  (>1000 holders) может занять несколько секунд.

## Step 5: Send invitation

Файл: `apps/api/app/modules/users/router.py:274-329`,
`apps/api/app/modules/users/invitations_service.py:68-190`.

```http
POST /api/v1/users/invitations/bulk
{
  "items": [
    {"email": "newcomer@example.com"},
    {"email": "another@example.com"}
  ]
}

→ 201
{
  "created": [
    {
      "email": "newcomer@example.com",
      "invitation_id": "uuid",
      "invite_url": "https://app.kml.kz/accept-invite?token=190char-secure-random",
      "expires_at": "2026-07-03T..."  // default 3 days
    }
  ],
  "skipped_existing": [
    {"email": "old@example.com", "reason": "already_in_tenant"}
  ],
  "invalid": []
}
```

**Side effects:**
1. Email validation: regex `^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$`, max 320 chars.
2. Skip: уже в tenant, или pending invitation существует.
3. Create **pending** User row (`is_active=False`, `password_hash=NULL`,
   `role="student"`).
4. Create **UserInvitation** row with `secrets.token_urlsafe(24)`
   (~190 bits entropy).
5. `expires_at = now() + tenant_settings.invite_expiry_days`
   (default 3, range 1-30).

**Важно:** **email НЕ отправляется**. Endpoint возвращает
`invite_url` для методолога, который копирует его в Slack/Telegram/email
**вручную**. Это **осознанное** решение для v1.0 (нет SMTP, нет
SendGrid). Упомянуто в `AGENTS.md` "Domain context" секция.

**Errors:**
- 403 если demo tenant (`assert_can_send_invite` в
  `core/demo_limits.py`)
- 422 если email невалидный
- 403 если `> 200 items` per request

### Resend

```http
POST /api/v1/users/invitations/{invitation_id}/resend
→ {
  "invitation_id": "new-uuid",
  "invite_url": "...",
  "expires_at": "...",
  "superseded_old_id": "old-uuid"
}
```

Создаёт НОВЫЙ invitation (свежий token), помечает старый как
`superseded`. **409** если старый уже `accepted`. **404** если
cross-tenant.

## Step 6: Accept invitation (public)

Файл: `apps/api/app/modules/users/invitations_router.py:39-80`,
`apps/api/app/modules/users/invitations_service.py:336-427`.

```http
GET /api/v1/invitations/{token}     # no auth
→ {
  "email": "newcomer@example.com",
  "tenant_name": "Acme Corp",
  "role": "student",
  "expires_at": "2026-07-03T...",
  "valid": true,
  "reason_if_invalid": null,
  "requires_personnel_number": false
}

POST /api/v1/invitations/{token}/accept   # no auth
{
  "first_name": "Иван",
  "last_name": "Иванов",
  "password": "StrongPass123!",
  "personnel_number": "EMP001"   // optional
}

→ 200
{
  "user_id": "uuid",
  "tenant_id": "uuid",
  "role": "student",
  "access_token": "jwt-here",
  "refresh_token": null
}
```

**Side effects (транзакция):**
1. **404** if token not found.
2. **410 Gone** if status ∈ {accepted, expired, revoked, superseded}.
3. **410** if `expires_at < now` (lazy-expires to "expired" first).
4. **422** if invitation has `personnel_number` but caller didn't
   supply one (soft 2FA — staff import binds invitation to a
   specific personnel_number).
5. **403** if personnel_number mismatch.
6. **500** if `user_id` FK missing or tenant mismatch.
7. Activate user: set `first_name`, `last_name`, persist
   `personnel_number` if needed, hash password with `argon2`,
   set `is_active=True`, `status='active'`, `last_login=now()`.
8. Mark invitation `accepted`, fill `accepted_at`, `accepted_ip`
   (X-Forwarded-For aware), `accepted_user_agent`.
9. Issue JWT via `create_access_token({sub, tenant_id, roles})` and
   return for auto-login.

**Auto-login:** `access_token` в ответе → frontend сохраняет в
`localStorage.kamilya_auth` и редиректит на `/dashboard`. **Без
повторного ввода пароля** — magic link pattern.

## Step 7: Take course + certificate

Файл: `apps/api/app/modules/courses/router.py:405-466`.

```http
POST /api/v1/courses/{id}/complete
→ {
  "status": "completed",
  "certificate_number": "KML-2026-ABC123"
}
```

**Side effects:**
1. Mark `Enrollment.status = 'completed'`, `completed_at = now()`.
2. Call `issue_certificate(course_id, user_id)` из
   `certificates/service.py` — INSERT в `certificates` с
   generated `certificate_number`, `pdf_path` сгенерированный
   в `certificates/pdf.py` (FPDF).
3. Idempotent: повторный вызов = тот же certificate_number.

**Public verify:** `GET /api/v1/certificates/verify/{number}` —
без auth, ищет по `certificate_number`. Возвращает `{valid: bool,
holder_name, course_title, issued_at, ...}`. (После Bug 1 fix —
404 на unknown number, не 500.)

## Live state snapshot (2026-06-30 10:30)

Из smoke через `POST /auth/demo-login {"role": "admin"}`:

| Resource | Count | Notes |
|---|---|---|
| Courses | 7 | 3 published, 4 draft; 1 создан в smoke-test ("Smoke-test course 2026-06-30") |
| Positions | 2 | "Главный" (legacy) + "Smoke Position 2026-06-30" (created during smoke) |
| Department | 2 | "IT" + legacy (cp1251 encoding, can't read in PowerShell) |
| Enrollments | 1 | total; 0 completed |
| Quizzes | 2 | attached to 2 lessons |
| AI jobs | 8 | 4 completed, 4 failed (2 pre-fix pgvector, 1 no-embeddings, 1 Qwen 502) |
| Invitations | 0 | none created yet |
| Certificates | 0 | none issued (because no completions) |
| PositionCourse bindings | 4 | включая binding из smoke-test (Course `b70dc39e-...` → Position `644fc786-...`) |

## Где живёт каждая фича (file map)

```
apps/api/app/
├── core/
│   ├── auth.py             # JWT encode/decode, get_current_user, require_role
│   └── config.py           # API_PREFIX, JWT_*, TELEGRAM_*, LLM_*
├── modules/
│   ├── ai/
│   │   ├── router.py       # /ai/generate-course, /ai/jobs/{id}, /ai/chat
│   │   ├── pipeline.py     # run_generation_pipeline (asyncio task)
│   │   ├── llm_client.py   # ResilientLLMClient, LLMProviderConfig, failover
│   │   ├── job_service.py  # create_ai_job, update_job_status
│   │   └── budget.py       # check_and_charge_llm_budget
│   ├── courses/
│   │   ├── router.py       # CRUD + review + publish + complete
│   │   └── schemas.py
│   ├── users/
│   │   ├── router.py              # invitations admin endpoints
│   │   ├── invitations_router.py  # public /invitations/{token} (no auth)
│   │   ├── invitations_service.py # bulk_create, resend, accept
│   │   ├── staff_import_router.py # /admin/staff/import/{preview,commit}
│   │   └── staff_import_service.py# parse_xlsx/csv, commit transaction
│   ├── positions/
│   │   ├── router.py              # CRUD + /courses + /assign
│   │   ├── batch_service.py       # recompute_position_holders
│   │   ├── assignment_service.py  # recompute_enrollments (kernel)
│   │   ├── tasks.py               # apply_rules_for_users_task (Celery)
│   │   └── models.py
│   └── certificates/
│       ├── router.py       # issue_certificate, verify
│       ├── service.py      # generate_certificate_number
│       └── pdf.py          # FPDF generation
└── workers/
    └── celery_app.py       # broker=Upstash Redis, queue=celery
```

## Известные дыры (на 2026-06-30)

1. **No `POST /admin/staff/apply-rules`** (manual retroactive
   trigger). Только через `import/commit`. Нужно отдельный endpoint
   если методолог захочет re-run apply-rules для уже импортированных
   пользователей после смены правил.
2. **Course publish не проверяет `review_status`** (router.py:302).
   Admin может publish course с `pending` review.
3. **AI generation auto-enroll'ит только creator'а** (pipeline.py:418).
   Если target_audience это позиция — другие holders НЕ auto-enroll'ятся.
4. **No email service** (AGENTS.md "Domain context"). Все приглашения
   копируются вручную в Slack/Telegram.
5. **Demo tenant guard** — `assert_can_send_invite` блокирует
   invites в demo (чтобы не спамить).
6. **Telegram invite отсутствует** — Telegram это **login path** (через
   `/auth/check-code`), не invite channel.
7. **`chat_lesson_id` suggestion из `/ai/chat`** (router.py:388) не
   имеет endpoint'а для apply. Frontend предположительно зовёт
   update endpoint напрямую.

## Время ответа (типичное)

| Endpoint | Median | p95 |
|---|---|---|
| `GET /courses` | 80ms | 200ms |
| `POST /courses` | 120ms | 300ms |
| `POST /ai/generate-course` | 50ms (returns 202 immediately) | 80ms |
| AI generation full pipeline | 60-180s | 300s |
| `POST /admin/staff/import/preview` | 1-3s (parses xlsx) | 8s |
| `POST /admin/staff/import/commit` | 2-5s + Celery dispatch | 15s + apply-rules time |
| `POST /positions/{id}/courses` | 100-500ms (sync recompute) | 3s (large position) |
| `POST /users/invitations/bulk` | 200ms | 1s |
| `POST /invitations/{token}/accept` | 300ms | 1s |

## Известные gotchas (из Lessons.md)

- **Lesson 1:** `LLMProviderConfig.endpoint` overridable. `EmbeddingsClient`
  ДОЛЖЕН override на `/embeddings`.
- **Lesson 5b:** Celery + asyncpg event-loop trap. Используй
  `asyncio.run()` внутри task, не `loop.run_until_complete`.
- **Lesson 6 (Round 2 / login-bug):** UUID в JWT payload →
  stdlib json.dumps падает. `_json_safe_jwt_payload` нормализует на
  encode boundary. НЕ конвертируй `exp`/`iat` в isoformat —
  PyJWT verify_exp ожидает int.
- **Lesson 17 (R3 / R7):** `TokenResponse.user` — это AuthUser shape
  (role, tenant, full_name), не UserResponse. Используй
  `build_user_payload` helper.
- **Lesson 19 (smoke):** Production schema drift. Migrations не
  run в проде (нет `alembic upgrade head` в startCommand). Делай
  diff `information_schema.columns` vs `Base.metadata` перед каждым
  deploy.
