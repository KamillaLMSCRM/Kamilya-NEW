# Kamilya LMS — Штатное расписание: Импорт (Methodologist's workflow)

Дата: 2026-06-30. Подробный walkthrough что происходит когда
**методолог** загружает штатку (xlsx/csv) и что с этим можно
делать. Основано на коде (`apps/api/app/modules/users/staff_import_*`
+ `apps/web/src/app/admin/staff/page.tsx`) + live smoke через
Python `urllib` против prod.

**Audience:** методолог, новый разработчик, future agent.

## TL;DR

```text
[1] Методолог открывает /admin/staff -> таб «Импорт»
[2] Выбирает .xlsx / .csv (10 MB max) -> upload
[3] Backend парсит, нормализует колонки (RU + EN)
[4] Backend матчит против текущей БД:
    - новая (personnel_number не существует) -> action="create"
    - существующая, что-то поменялось -> action="update"
    - существующая, ничего не поменялось -> action="skip"
[5] Preview показывает summary + таблицу (с notes про изменения)
[6] Методолог проверяет, кликает «Применить» (с confirm)
[7] Commit (single transaction):
    - auto-create Position для новых (department, position)
    - update существующих (first_name, last_name, email, phone, position_id)
    - create новых (role="student", password_hash=NULL, is_active=True)
    - tracked affected_user_ids (new + position-changed)
[8] Backend dispatch Celery: positions.apply_course_rules
[9] UI показывает <ApplyRulesProgress> banner (poll /status/{tid})
[10] Celery worker делает recompute_enrollments для каждого user
[11] Баннер исчезает когда state=SUCCESS/FAILURE
```

## File layout

| File | Lines | Purpose |
|---|---|---|
| `apps/api/app/modules/users/staff_import_service.py` | 625 | Парсинг файла, preview logic, commit transaction |
| `apps/api/app/modules/users/staff_import_router.py` | 293 | HTTP endpoints + Celery dispatch + status polling |
| `apps/api/app/modules/positions/tasks.py` | 107 | `apply_rules_for_users_task` Celery task |
| `apps/api/app/modules/positions/assignment_service.py` | 180 | `recompute_enrollments` kernel |
| `apps/web/src/app/admin/staff/page.tsx` | 675 | UI: file picker, preview, commit, apply-rules banner |

## Поддерживаемые форматы файлов

| Расширение | Поддержка | Как читается |
|---|---|---|
| `.csv` | ✅ | UTF-8-sig / CP1251 / UTF-8 (с заменой) |
| `.xlsx` | ✅ | `openpyxl` read_only |
| `.xls` | ❌ (400) | "Старый формат .xls не поддерживается. Сохраните файл как .xlsx или .csv." |
| Другое | ❌ (400) | "Формат файла не поддерживается: {name}. Используйте .xlsx или .csv." |
| > 10 MB | ❌ (413) | "Файл слишком большой (макс. 10 МБ)" |
| Empty | ❌ (400) | "Файл пустой" |

## Recognized columns (case-insensitive, RU + EN)

Канонические имена в БД → алиасы из файла:

| Каноническое | Required? | Алиасы |
|---|---|---|
| `personnel_number` | **yes** | `табельный_номер`, `табельный номер`, `таб_номер`, `табельный№`, `employee_id`, `tab_no`, `tabno` |
| `first_name` | **yes** | `имя` |
| `last_name` | **yes** | `фамилия` |
| `department` | **yes** | `отдел`, `подразделение`, `цех` |
| `position` | **yes** | `должность` |
| `email` | no | `e-mail`, `почта` |
| `phone` | no | `телефон` |
| `hire_date` | no | `дата_приема`, `дата приема` (DD.MM.YYYY / DD/MM/YYYY / ISO) |

Если хотя бы одна required колонка отсутствует — backend возвращает
`missing_required_columns: [...]` в preview response (HTTP 200
с пустым items). UI показывает ошибку и не даёт commit'ить.

## Preview flow

### Request

```http
POST /api/v1/admin/staff/import/preview
Authorization: Bearer <methodologist-jwt>
Content-Type: multipart/form-data

file=<xlsx-or-csv>
```

### Что делает backend (псевдокод)

```python
1. Read file, validate size <= 10MB
2. parse_upload(filename, bytes) -> ParsedFile
   - dispatch: .csv -> parse_csv; .xlsx -> parse_xlsx
   - map headers via COLUMN_ALIASES (case-insensitive)
   - validate required columns exist
   - for each row:
     - extract fields via column_map
     - skip if all empty
     - validate required fields not empty
     - check duplicate personnel_number within file
     - parse hire_date (ISO / DD.MM.YYYY / DD/MM/YYYY)
3. If missing_required_columns: return without preview
4. build_preview(db, tenant_id, parsed):
   - load existing users in tenant (personnel_number NOT NULL)
   - load existing positions in tenant
   - for each parsed row:
     - find user by personnel_number (case-insensitive)
     - find position by (department, position) lower-cased
     - if user exists:
       - compare fields -> if no changes -> action="skip"
       - if any change -> action="update" + notes[]
     - else: action="create" + notes[] about new position
   - collect new_positions, new_departments
   - summary = {create, update, skip, new_positions, new_departments}
5. Return PreviewResponse (JSON)
```

### Response (200)

```json
{
  "items": [
    {
      "row_number": 2,
      "personnel_number": "EMP101",
      "first_name": "Иван",
      "last_name": "Петров",
      "department": "IT",
      "position": "Senior Developer",
      "email": "ivan.petrov@smoke.kml",
      "phone": "+7701000101",
      "action": "create",     // or "update" | "skip"
      "existing_user_id": null,
      "notes": ["новая должность: «Senior Developer» в «IT»"]
    }
  ],
  "new_positions": ["IT / Senior Developer", "Бухгалтерия / Chief Accountant"],
  "new_departments": ["Бухгалтерия"],
  "summary": {
    "create": 3,
    "update": 0,
    "skip": 0,
    "new_positions": 3,
    "new_departments": 1,
    "invalid_rows": 0
  },
  "invalid_rows": [],
  "missing_required_columns": [],
  "total_rows_in_file": 3
}
```

### Notes поле (человеко-читаемые изменения)

Для **create**: notes содержит "новая должность: «X» в «Y»" если
(department, position) pair новый.

Для **update**: notes содержит diff:
- "имя: «Старое» → «Новое»"
- "email: «old@x» → «new@x»"
- "новая должность: «X» (отдел «Y»)"

Для **skip**: notes = ["Без изменений"].

### Errors (preview)

| HTTP | Cause | Detail |
|---|---|---|
| 400 | Empty file | "Файл пустой" |
| 400 | File too big | (сначала идёт 413 ниже) |
| 400 | Parse error (ValueError) | Текст ошибки от ValueError |
| 400 | Other parse error | "Не удалось прочитать файл: {Type}: {msg}" |
| 413 | > 10 MB | "Файл слишком большой (макс. 10 МБ)" |
| 200 | Missing required columns | Body содержит `missing_required_columns` (НЕ ошибка HTTP) |
| 403 | Methodologist blocked | До commit 19c25b1. Сейчас methodologist разрешён. |

## Commit flow

### Request

```http
POST /api/v1/admin/staff/import/commit
Authorization: Bearer <methodologist-jwt>
Content-Type: multipart/form-data

file=<the-same-file>
```

### Что делает backend

```python
1. Same parsing as preview (rows + invalid_rows)
2. If missing_required_columns: 400
3. If invalid_rows: 422 with first 20 invalid rows
4. If no rows: 400 "Файл не содержит данных"
5. commit_import(db, tenant_id, parsed) in transaction:
   for each row:
     a. resolve/create Position (department, position)
        - if not exists: INSERT Position(level="", responsibilities="", requirements="", employee_count=0)
     b. resolve user by personnel_number
     c. if user exists:
        - update first_name/last_name/email/phone if changed
        - update position_id if changed + set is_active=True
        - count as "updated" if anything changed, "skipped" if not
        - add to affected_user_ids ONLY if position_id actually changed
     d. else (new user):
        - INSERT User(role="student", is_active=True, password_hash=NULL, status="active")
        - count as "created"
        - add to affected_user_ids (new user gets position, needs rules)
   COMMIT
6. If affected_user_ids non-empty: dispatch Celery
   apply_rules_for_users_task.delay(affected_user_ids)
7. Return counts + task_id
```

**Critical: All-or-nothing** — if any row fails, full rollback.

### Response (200)

```json
{
  "created": 3,
  "updated": 0,
  "skipped": 0,
  "positions_created": 3,
  "apply_rules_task_id": "e262b944-fb2f-444b-9581-25cdb89d04c2",
  "affected_user_count": 3
}
```

`apply_rules_task_id` = None если affected_user_count = 0 (т.е. ничего
не поменялось или только email/имя без position change).

### Errors (commit)

| HTTP | Cause | Detail |
|---|---|---|
| 400 | Empty file | "Файл пустой" |
| 400 | Missing required columns | "В файле отсутствуют обязательные колонки: X, Y" |
| 400 | No data rows | "Файл не содержит данных" |
| 400 | Parse error | "Не удалось прочитать файл: ..." |
| 413 | > 10 MB | "Файл слишком большой" |
| 422 | Invalid rows | `{"message": "...", "invalid_rows": [...], "total_invalid": N}` |
| 500 | Apply failed | "Ошибка применения: {Type}: {msg}" (после `db.rollback()`) |
| 403 | Methodologist blocked | До fix 19c25b1. Сейчас methodologist разрешён. |

## Apply-rules (Celery) flow

### Trigger

В `staff_import_router.py::import_staff_commit`, после успешного
`commit_import` и только если `affected_user_ids` не пустой:

```python
from app.modules.positions.tasks import apply_rules_for_users_task
async_result = apply_rules_for_users_task.delay(affected_user_ids)
task_id = async_result.id
```

**Если dispatch упал** (broker недоступен, worker offline):
- import всё равно считается успешным (200, created/updated counts)
- task_id = None
- В логах: "apply-rules dispatch failed for N users: {err}"
- Данные по юзерам консистентны, просто нет apply-rules пока
- Можно re-run руками через... **эндпоинта нет!** (Lesson 19 / Lesson
  в этом дне: "No POST /admin/staff/apply-rules for manual
  trigger")

### Что делает worker (Celery)

`apps/api/app/modules/positions/tasks.py:25-107` —
`apply_rules_for_users_task(user_ids: list[str])`:

```python
@celery_app.task(name="positions.apply_course_rules")
def apply_rules_for_users_task(user_ids):
    async def _run():
        async with async_session() as db:
            results = {"users_processed": 0, "added": 0, ...}
            for raw_id in user_ids:
                try:
                    result = await apply_rules_for_users(db, [user_uuid])
                    results["added"] += result.added
                    ...
                except Exception as e:
                    results["failed_user_ids"].append(raw_id)
                    logger.exception("apply_rules failed for user %s", raw_id)
            return results
    return asyncio.run(_run())
```

`apply_rules_for_users` (`batch_service.py`) для каждого user:
- загружает user → position → department
- собирает `expected` courses: union PositionCourse ∪ DepartmentCourse
  (position wins on collision)
- diff с current `Enrollment` rows (split by source: rule vs manual)
- INSERT to_add (expected - rule - manual)
- DELETE to_remove (rule rows not in expected, status≠completed)
- **никогда** не трогает manual enrollments или completed rule rows

### Polling

```http
GET /api/v1/admin/staff/apply-rules/status/{task_id}
```

Response (Celery state):

```json
{
  "task_id": "e262b944-fb2f-444b-9581-25cdb89d04c2",
  "state": "SUCCESS",     // PENDING|RECEIVED|STARTED|SUCCESS|FAILURE|RETRY|REVOKED
  "ready": true,
  "successful": true,
  "failed": false,
  "result": {
    "users_processed": 3,
    "added": 0,           // 0 потому что у новых positions нет course bindings
    "removed": 0,
    "skipped_manual": 0,
    "protected_completed": 0,
    "failed_user_ids": [],
    "errors": []
  },
  "error": null
}
```

`<ApplyRulesProgress>` UI component (`apps/web/src/components/ui/ApplyRulesProgress.tsx`)
поллит каждые 1-2s пока `state ∈ {PENDING, RECEIVED, STARTED, RETRY}`.
Когда `state = SUCCESS` или `FAILURE` — перестаёт поллить.

## Что можно делать с штаткой после импорта

### 1. Просмотр оргструктуры

`GET /api/v1/admin/staff/structure` — иерархия по департаментам →
позициям → сотрудникам. UI таб «Структура».

Также `GET /api/v1/positions` возвращает плоский список позиций.

### 2. Привязка курса к должности (запускает enrollments)

`POST /api/v1/positions/{position_id}/courses`:
```json
{ "course_id": "uuid", "required": true }
```

Синхронно делает `recompute_enrollments` для всех holder'ов этой
позиции. Возвращает PositionResponse с `re_enrolled: N`.

**Пример:** после нашего smoke (3 новых позиции без курсов) — если
привязать курс к "Senior Developer", то user Иван Петров
(EMP101) сразу получит `enrollment` row.

### 3. Назначение позиции сотруднику (move between positions)

`POST /api/v1/positions/{position_id}/assign/{user_id}` — single-user
recompute. Сейчас `require_role` = `get_current_user` (no role check)
— это **TBD**, ADR говорит methodologist.

### 4. Edit позиции (level, responsibilities, requirements)

`PUT /api/v1/positions/{position_id}`:
- можно править level, responsibilities, requirements, department
- **каждое** изменение responsibilities/requirements snapshot'ится
  в `PositionJDVersion` (audit trail)
- если `req.course_ids` в payload — full recompute

### 5. Edit должностной инструкции (JD) — Job Description

`GET /api/v1/positions/{id}/jd-versions` — список версий
`GET /api/v1/positions/{id}/jd-preview` — последняя версия
`POST /api/v1/positions/{id}/jd-versions/{vid}/restore` — rollback

### 6. Generate JD через AI

`POST /api/v1/positions/analyze-jd` — анализ существующей JD
`POST /api/v1/positions/generate-jd-from-name` — генерация с нуля
(по названию должности через Qwen)
`POST /api/v1/positions/bulk-analyze-jd` — batch по всем позициям

### 7. Recommended courses (AI)

`POST /api/v1/positions/{id}/suggest-courses` — какие курсы подходят
для этой позиции (AI)
`POST /api/v1/positions/{id}/suggest-onboarding-quiz` — quiz для
онбординга
`POST /api/v1/positions/{id}/create-courses` — создать несколько
курсов сразу + привязать к позиции

### 8. Onboarding quiz

`GET /api/v1/positions/{id}/onboarding-quiz` — quiz при приёме
`POST /api/v1/positions/{id}/recalc-employees` — refresh
`employee_count` для позиции (полезно после import — обычно
`employee_count=0` сразу после commit, обновляется на assign)

### 9. Audit log

`GET /api/v1/audit/logs?entity_type=position&entity_id={id}` —
кто менял, когда, что именно. Полезно после массового import.

## Связь с apply-rules (B1c) — картина целиком

```
Import staff (Step 3)
   ↓
Commit creates positions + users (sync)
   ↓
affected_user_ids = [new users + users whose position changed]
   ↓
Dispatch Celery apply_rules_for_users_task
   ↓
Celery worker processes each user:
   - load user.position -> load PositionCourse bindings
   - load user.position.department -> load DepartmentCourse bindings
   - INSERT enrollment rows for new expected courses
   - DELETE enrollment rows for courses no longer expected
   - skipped_manual, protected_completed counters
   ↓
UI banner poll: state -> SUCCESS / FAILURE
```

**Что НЕ делает import:**
- не привязывает курсы к позициям (нужно POST /positions/{id}/courses)
- не генерирует JD (нужно POST /positions/{id}/generate-jd-from-name)
- не создаёт онбординг quiz
- не устанавливает password (user создан с `password_hash=NULL` —
  вход через Telegram или invitation, не через password)
- не отправляет email (нет SMTP в v1.0, AGENTS.md "Domain context")
- не повышает role (всегда "student"; повышение через
  `POST /v1/users/{id}/role`)

## Edge cases & gotchas

### 1. Duplicate personnel_number ВНУТРИ файла

`parse_csv` и `parse_xlsx` оба проверяют `seen_pn` (case-insensitive
normalized). Дубликат в файле → row в `invalid_rows[]`, но
остальные строки парсятся нормально.

### 2. User без personnel_number (например, заведён через Telegram)

`build_preview` грузит users где `personnel_number IS NOT NULL` —
user без табельного номера **не** матчится. Если в файле есть
такой personnel_number — он создаст **нового** user, не обновит
существующего. Это by design: табельный номер = primary key для
import.

### 3. Position меняется — это trigger для apply-rules

`commit_import` добавляет user'а в `affected_user_ids` ТОЛЬКО если
`position_id` реально поменялся (не только имя/email). Это
оптимизация: name/email change не требует recompute.

### 4. employee_count обновляется асинхронно

`commit_import` создаёт Position с `employee_count=0`. Реальный
count обновляется:
- в `POST /positions/{id}/assign/{user_id}` (синхронно)
- в `POST /positions/{id}/recalc-employees` (явный пересчёт)
- в `recompute_enrollments` для affected user'ов (частично)

После import рекомендуется дёрнуть `POST /v1/positions/recalc-employees`
если UI показывает `employee_count=0` для недавно импортированных
позиций.

### 5. .xls НЕ поддерживается

Старый бинарный Excel (BIFF) — reject. Если HR прислал .xls, попроси
сохранить как .xlsx (Excel: "Save As → Excel Workbook").

### 6. CSV с BOM (UTF-8-sig) — OK

`parse_csv` сначала пробует `utf-8-sig` (UTF-8 с BOM, экспорт из
русского Excel часто такой). Если не выходит — `cp1251` (старая
кодировка). Если и это не выходит — `utf-8` с заменой невалидных
символов.

### 7. hire_date в разных форматах

`parse_hire_date` принимает:
- ISO: `2026-01-15`
- DD.MM.YYYY: `15.01.2026` (русский)
- DD/MM/YYYY: `15/01/2026` (европейский)
- DD-MM-YYYY: `15-01-2026`
- 2-digit year: `15.01.26` → `2026` если year < 50, иначе `19xx`

Невалидный формат → `hire_date = None` (row помечается как invalid).

### 8. Demo-tenant guard

`assert_can_send_invite` блокирует invite в demo tenant (чтобы
prospect не спамил). Import не блокируется — только invitation.

## Live smoke (2026-06-30 10:55)

Загрузил CSV с 3 строками как `methodologist` demo user:

```csv
personnel_number,first_name,last_name,department,position,email,phone
EMP101,Иван,Петров,IT,Senior Developer,ivan.petrov@smoke.kml,+7701000101
EMP102,Анна,Сидорова,IT,QA Engineer,anna.sidorova@smoke.kml,+7701000102
EMP103,Сергей,Кузнецов,Бухгалтерия,Chief Accountant,sergey@smoke.kml,+7701000103
```

**Preview** (POST /admin/staff/import/preview):
```
items: 3 строки, все action="create"
new_positions: 3 (Senior Developer, QA Engineer, Chief Accountant)
new_departments: 1 (Бухгалтерия; IT уже был)
summary: create=3, update=0, skip=0, new_positions=3, new_departments=1
```

**Commit** (POST /admin/staff/import/commit):
```
created: 3
positions_created: 3
apply_rules_task_id: e262b944-fb2f-444b-9581-25cdb89d04c2
affected_user_count: 3
```

**Apply-rules polling** (GET /admin/staff/apply-rules/status/...):
```
state: SUCCESS
users_processed: 3
added: 0  (потому что у новых positions нет course bindings)
removed: 0
errors: []
```

**Final state** (GET /api/v1/positions):
- Было 2 positions (Главный, Smoke Position)
- Стало 5: + Senior Developer, + QA Engineer, + Chief Accountant
- Все 3 новые имеют `employee_count=0` сразу после import (нужен
  recalc-employees или assign)

`enrollments/stats`: `total: 1` (старая, не наша — потому что
новые positions не имеют `PositionCourse` bindings).

**Чтобы получить реальные enrollments для новых user'ов, методолог
должен:**
1. Создать или привязать курсы к новым позициям:
   `POST /api/v1/positions/{senior_developer_id}/courses` для каждой
2. Или использовать AI suggested courses:
   `POST /api/v1/positions/{id}/suggest-courses` → approve →
   `POST /api/v1/positions/{id}/create-courses` (создаёт несколько
   сразу)
3. После привязки apply-rules Celery task автоматически создаст
   enrollments для всех holder'ов

## TL;DR для UI (что видит методолог)

| Действие | UI path | Endpoint |
|---|---|---|
| Импорт | /admin/staff → таб «Импорт» | POST /admin/staff/import/{preview,commit} |
| Apply-rules progress | баннер после commit | GET /admin/staff/apply-rules/status/{tid} |
| Структура | /admin/staff → таб «Структура» | GET /admin/staff/structure + GET /positions |
| Правила (apply rules вручную) | /admin/staff → таб «Правила» | (сейчас только через import/commit; POST /admin/staff/apply-rules отсутствует) |
| Привязать курс к должности | /positions/[id] → "Добавить курс" | POST /positions/{id}/courses |
| AI suggested courses | /positions/[id] → "AI: рекомендованные курсы" | POST /positions/{id}/suggest-courses |
| Generate JD | /positions/[id] → "Сгенерировать JD" | POST /positions/{id}/generate-jd-from-name |
| Recalc employees | /positions/[id] → "Recalc" | POST /positions/{id}/recalc-employees |

## Известные баги / TODO

1. **Нет `POST /admin/staff/apply-rules`** для manual trigger. Если
   apply-rules упал (worker offline, broker down) — нужен
   ручной re-trigger. **Пока** — только ждать пока worker
   восстановится и import заново.
2. **`employee_count=0` после import** пока методолог не дёрнет
   `recalc-employees` или `assign`. UI должен показывать
   "0 (обновить)" индикатор.
3. **`is_active=True` для new user без password** — user создан
   активным но без password. Может войти только через Telegram-код
   (если у него есть telegram_id) или invitation (если
   методолог пригласит). Не может войти через password.
4. **`position_changed` только для position_id change** —
   если у user'а в файле другая должность но та же position_id
   (т.е. тот же position row), он не попадёт в
   affected_user_ids. По дизайну — ему не нужен apply-rules.
5. **Дубликат (department, position) в разных cases** — если в
   файле "IT / Senior Developer" и в существующих "IT / Senior
   Developer" с разным регистром, они **сматчатся**
   (case-insensitive). Это by design.
6. **Нет rollback'а для apply-rules** — если commit прошёл, а
   Celery упал, юзеры созданы, но enrollments пустые. Re-trigger
   нужен (пока не существует).
