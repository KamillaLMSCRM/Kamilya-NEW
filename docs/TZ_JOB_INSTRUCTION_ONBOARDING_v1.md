# ТЗ v1.0 — Онбординг-курс по должностной инструкции (ДИ)

**Дата:** 2026-06-30
**Статус:** Согласовано с архитектором (Askar) — **К РЕАЛИЗАЦИИ**
**Связанные документы:**
- `TZ.md` (главный)
- `docs/TZ_COURSE_ASSIGNMENT_ACCESS_v1.md` (4 уровня привязки курсов — это upstream)
- `docs/adr/0011-*` (Position/User refactor)
- `docs/adr/0012-rbac-admin-vs-methodologist.md` (RBAC)
- `docs/LESSONS.md` (Уроки 1-23, особенно про embeddings и ingestion)

> Этот документ — вход для исполнителя (AI-агента или разработчика): требования
> обязательны, реализация рекомендуемая. Любое отклонение — через обсуждение с
> архитектором.

---

## 0. TL;DR

> **К каждой позиции привязывается ровно одна должностная инструкция (ДИ).
> По этой ДИ AI генерирует онбординг-курс строго по её содержимому — без
> «поиска похожих», без расширения контекста. Курс автоматически назначается
> на эту позицию (level 3). Сотрудник при назначении на позицию получает курс.
> При обновлении ДИ курс НЕ перегенерируется автоматически — показывается
> баннер, методолог решает вручную.**

> **Зависимость от `TZ_COURSE_ASSIGNMENT_ACCESS_v1.md`:** этот документ
> описывает flow «ДИ → position → course». Реализация `attach_course_to_department`
> (level 2 в общей модели) — **общая** для course-assignment и для
> onbording-курса, потому что при генерации онбординг-курса он сначала
> привязывается к отделу, потом к позиции. **Эпик «nav fixes» 2026-06-30**
> (commits `03c5658`/`3706785`/`d7ed4ac`/`a32d76a`) починил `DepartmentLocator`
> в `apps/api/app/modules/departments/router.py` — UI «Привязка курса» к отделу
> больше не падает на 422 для Excel-импортированных тенантов. Эти фиксы
> критичны и для онбординг-flow: методолог, который загружает ДИ и нажимает
> «Сгенерировать онбординг-пакет», пройдёт через ту же привязку курса к
> отделу. Подробности — в `TZ_COURSE_ASSIGNMENT_ACCESS_v1.md` §2.5
> (блок «✅ Реализация (`03c5658`...)»).

---

## 1. Модель данных

### 1.1. Категория документа

`Document` — общая корзина для PDF/DOCX/MD/TXT/CSV/Excel. Сейчас без категорий.

**Добавляем поле `category`** (миграция `0041_documents_category.py`):

```sql
ALTER TABLE documents
    ADD COLUMN category VARCHAR(32) NOT NULL DEFAULT 'general';

ALTER TABLE documents
    ADD CONSTRAINT ck_documents_category
    CHECK (category IN ('general', 'job_instruction'));

CREATE INDEX ix_documents_tenant_category
    ON documents (tenant_id, category)
    WHERE category = 'job_instruction';
```

**Решения:**
- `'general'` — всё что сейчас есть (backward compatible default)
- `'job_instruction'` — ДИ для позиции
- Index partial — потому что 99% документов `'general'`, partial index быстрее

**Кто может менять category:** methodologist (admin) — при загрузке ДИ специальным flow; нельзя «просто так» сменить категорию уже загруженного документа.

### 1.2. Связь Position ↔ ДИ (single FK)

**Добавляем поле `Position.instruction_document_id`** (миграция `0042_position_instruction.py`):

```sql
ALTER TABLE positions
    ADD COLUMN instruction_document_id UUID
        NULL REFERENCES documents(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX uq_positions_tenant_instruction
    ON positions (tenant_id, instruction_document_id)
    WHERE instruction_document_id IS NOT NULL;
```

**Решения:**
- **Одна позиция = одна ДИ** (per architect decision 2026-06-30). Если нужны несколько ДИ — это v1.1.
- `ON DELETE SET NULL` — если ДИ удалена, позиция остаётся без ДИ (показывается баннер «требуется загрузить ДИ»).
- UNIQUE index на `(tenant_id, instruction_document_id)` — защита от того, чтобы одна ДИ была привязана к двум позициям. Если методолог хочет переиспользовать ДИ — нужно скопировать документ (UI делает копию через POST /documents/{id}/duplicate).

**В `Position.models`:** relationship `instruction_document: Document | None`.

### 1.3. Аудит: какой курс сгенерён по какой ДИ

**Добавляем поле `Course.source_instruction_id`** (миграция `0043_course_source_instruction.py`):

```sql
ALTER TABLE courses
    ADD COLUMN source_instruction_id UUID
        NULL REFERENCES documents(id) ON DELETE SET NULL;

CREATE INDEX ix_courses_source_instruction
    ON courses (source_instruction_id)
    WHERE source_instruction_id IS NOT NULL;
```

**Зачем:**
- Аудит: «этот курс сгенерён по ДИ X» — для compliance и для UI баннера при изменении ДИ.
- Версионирование: когда ДИ обновится, можно показать «курс основан на ДИ версии от 2026-06-15, текущая версия — 2026-06-30».
- Не используется для runtime-логики (привязка студентов идёт через `position_courses`, не через `source_instruction_id`).

---

## 2. Pipeline: режим `position_onboarding`

### 2.1. Текущее состояние

`POST /v1/ai/generate-course` принимает:

```python
class AIGenerateRequest(BaseModel):
    course_id: UUID | None = None
    documents: List[str]           # document IDs
    target_audience: str = ""
    num_modules: int = 3
    language: str = "ru"
    tone: str = "professional"
```

Architect внутри может вызывать `search_documents()` для расширения контекста — это **прямо противоречит** требованию «только эта ДИ».

### 2.2. Новый режим

Добавляем discriminated union:

```python
class AIGenerateRequest(BaseModel):
    # Существующие поля:
    course_id: UUID | None = None
    documents: List[str] = []
    target_audience: str = ""
    num_modules: int = 3
    language: str = "ru"
    tone: str = "professional"

    # Новые поля для position_onboarding:
    mode: Literal["general", "position_onboarding"] = "general"
    position_id: UUID | None = None
    quiz_pass_score: int | None = None  # 50..95, default = tenant_settings.quiz_pass_threshold
```

### 2.3. Контракт endpoint'а

```
POST /v1/ai/generate-course
{
  "mode": "position_onboarding",
  "position_id": "uuid",
  "num_modules": 2,
  "language": "ru",
  "quiz_pass_score": 80
}
```

**Поведение backend:**

1. Если `mode == "general"` — поведение как сейчас (без изменений).
2. Если `mode == "position_onboarding"`:
   - `position_id` обязателен → иначе `422 POSITION_ID_REQUIRED`.
   - Загрузить `Position`. Если `tenant_id != user.tenant_id` → `404 POSITION_NOT_FOUND` (cross-tenant).
   - Если `Position.instruction_document_id IS NULL` → `422 INSTRUCTION_REQUIRED` с детальным сообщением:
     ```json
     {
       "code": "INSTRUCTION_REQUIRED",
       "detail": "К позиции 'Бухгалтер' не привязана должностная инструкция. Загрузите ДИ в /positions/{id}?tab=instructions",
       "position_id": "uuid",
       "upload_url": "/positions/{id}?tab=instructions"
     }
     ```
   - Загрузить `Document`. Если `category != 'job_instruction'` → `422 INSTRUCTION_INVALID` (защита от race: документ заменили).
   - `documents = [str(Position.instruction_document_id)]` — **ровно один** документ.
   - `target_audience = Position.title` — derived, не input.
   - `num_modules` clamp 1..5 (ДИ обычно 1-3 страницы, не сделать 10 модулей).
   - `quiz_pass_score`: если не указан, берётся из `tenant_settings.quiz_pass_threshold`. Если указан — clamp 50..95.
3. Создаёт `AIJob` как обычно, запускает pipeline.

**RBAC:** `require_role("superadmin", "admin", "org_admin", "teacher")` — methodologist + admin, как у `/ai/generate`.

### 2.4. Модификация system prompt Architect'а

**Файл:** `packages/ml-pipeline/prompts/architect/system.md` (или эквивалент)

Добавить секцию в начало:

```markdown
## Mode: position_onboarding

If the pipeline was started in `position_onboarding` mode, the input
documents list contains EXACTLY ONE document — a job instruction (ДИ)
for a specific position. Your task is to generate an onboarding course
STRICTLY based on this document's contents.

Rules:
- Do NOT call `search_documents()` — you have exactly one document, use it.
- Do NOT invent topics not present in the ДИ. If the ДИ mentions only
  three procedures, the course must contain those three procedures, no more.
- If the ДИ is too sparse for the requested `num_modules`, reduce the
  number of modules rather than inventing filler content. Set
  `actual_num_modules` in the output to the reduced count.
- Every lesson must cite the ДИ section it is based on (cite as
  `«ДИ, раздел X.Y»` in lesson introduction).
- The quiz for each lesson must test ONLY what is in that lesson, with
  answers traceable to the ДИ.
```

**В Python** (`app/modules/ai/architect.py`):
- Передавать в `_build_system_prompt` флаг `is_position_onboarding: bool`.
- Если флаг = True, инструмент `search_documents` **запрещён** (проверка в `_check_tool_allowed`).
- Tool list для этого режима = `[list_documents, read_document]` (только чтение того что дали).

### 2.5. Запись результата

После успешной генерации:

1. Создаётся `Course` как обычно (`courses` table).
2. Устанавливается `Course.source_instruction_id = instruction_document_id`.
3. **Автоматически привязывается к позиции** через `POST /v1/positions/{id}/courses` (level 3) — внутри `_safe_pipeline`, после `db.commit()` курса.

   Это значит: новый сотрудник, назначенный на эту позицию через `apply_rules_for_users`, сразу получит курс.

4. Если ДИ версия изменилась **позже** — см. §3.3.

### 2.6. Audit log

Действие `AI_COURSE_GENERATED_FROM_INSTRUCTION` пишется в `audit_log` с полями:
- `actor_user_id`, `tenant_id`
- `course_id`, `position_id`, `instruction_document_id`
- `instruction_document_version` (= `Document.updated_at`)
- `num_modules`

---

## 3. UX

### 3.1. Загрузка ДИ к позиции

**Страница:** `/positions/[id]` (route уже есть, добавляем вкладку).

**Tabs:**
- Обзор (уже есть)
- Курсы (уже есть)
- **Должностные инструкции** (новый)
- История (опц.)

**Вкладка «Должностные инструкции»:**

```
┌─────────────────────────────────────────────────────────┐
│  Должностная инструкция                                  │
│                                                          │
│  ┌─ Текущая ДИ ─────────────────────────────────────┐   │
│  │ 📄 ДИ_Бухгалтер_v3.pdf                          │   │
│  │ Загружена: 2026-06-15 • Размер: 240 KB          │   │
│  │ [📥 Скачать] [🔄 Заменить] [🗑 Удалить]         │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  Если ДИ не загружена:                                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Нет должностной инструкции                       │   │
│  │  Без ДИ нельзя сгенерировать онбординг-курс.      │   │
│  │  [📎 Загрузить ДИ]                                │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Загрузка:**
- Кнопка «📎 Загрузить ДИ» → dialog → file picker → категория `job_instruction` (зашита в dialog title).
- Использует существующий `POST /v1/documents` (расширить схему: `category: Literal["general", "job_instruction"]`).
- После успешной загрузки → `PATCH /v1/positions/{id}` с `instruction_document_id`.

**Заменить ДИ:**
- Кнопка «🔄 Заменить» → confirm dialog: «Текущий онбординг-курс останется без изменений. Загрузить новую ДИ?»
- При подтверждении — старый документ `category` сбрасывается на `'general'` (или остаётся как есть — решаем: оставить как есть, потому что документ может быть полезен).

**Удалить ДИ:**
- Кнопка «🗑 Удалить» → confirm dialog с предупреждением: «Курс, сгенерированный по этой ДИ, останется. Сотрудники, назначенные на эту позицию, продолжат его проходить. Удалить ДИ?»
- `DELETE /v1/documents/{id}` + `PATCH /v1/positions/{id}` с `instruction_document_id: null`.

### 3.2. Генерация онбординг-курса

**Триггер:** в `/positions/[id]?tab=instructions` кнопка «🎓 Сгенерировать онбординг-курс».

**Visibility:**
- Кнопка disabled если `instruction_document_id IS NULL`.
- Tooltip: «Сначала загрузите ДИ».

**Click → dialog:**

```
┌─ Сгенерировать онбординг-курс ────────────────────┐
│                                                    │
│  По ДИ: 📄 ДИ_Бухгалтер_v3.pdf (240 KB)           │
│                                                    │
│  Количество модулей:  [ 1 ] [ 2 ] [✓3] [ 4 ] [5]  │
│  (рекомендуем 2-3 для типовой ДИ)                  │
│                                                    │
│  Язык:  [✓RU] [ KK ] [ EN ]                        │
│                                                    │
│  Проходной балл для тестов: [80]%                  │
│  (по умолчанию из настроек тенанта, 50-95)         │
│                                                    │
│  ℹ️ Курс будет автоматически назначен на           │
│     позицию «Бухгалтер». Сотрудники получат        │
│     его при назначении.                            │
│                                                    │
│         [Отмена]  [🚀 Запустить генерацию]         │
└────────────────────────────────────────────────────┘
```

**Submit:**
1. `POST /v1/ai/generate-course { mode: "position_onboarding", position_id, num_modules, language, quiz_pass_score }`.
2. Redirect на `/courses/{new_course_id}/edit` (как сейчас для обычной генерации).
3. На `/positions/[id]` появляется баннер: «✅ Онбординг-курс создан → [Открыть]».

### 3.3. Баннер при обновлении ДИ

**Триггер:** `Document.updated_at > Course.created_at` И `Course.source_instruction_id == Document.id`.

**Где показывать:**
- На `/positions/[id]` — баннер сверху.
- В `/courses/[id]/edit` — если `Course.source_instruction_id` указывает на документ с более новой версией — badge в header.

**UI:**

```
┌──────────────────────────────────────────────────────────────┐
│  ⚠️ ДИ обновилась                                            │
│  ДИ_Бухгалтер_v3.pdf → ДИ_Бухгалтер_v4.pdf (2026-06-30)      │
│  Текущий онбординг-курс основан на старой версии.             │
│  [♻️ Регенерировать курс]  [👁 Посмотреть что изменилось]    │
└──────────────────────────────────────────────────────────────┘
```

**«Регенерировать»:**
- Confirm: «Создать новую версию курса? Старый курс останется для тех, кто уже начал. Новые сотрудники получат обновлённый.»
- Если подтверждено → новый `POST /v1/ai/generate-course { mode: "position_onboarding", position_id, quiz_pass_score: <из старого курса> }`.
- Новый курс → `Course.source_instruction_id = instruction_document_id`, новая дата `created_at`.
- **Старый курс НЕ удаляется**, остаётся привязан к позиции как ещё одна запись `position_courses` (то есть и старый, и новый курс будут у position — сотрудники, начавшие старый, заканчивают его; новые сотрудники получают оба, но это OK — duplicates).

   Альтернатива (на потом): replace strategy (снять старый, поставить новый). Для v1.0 — additive (проще, безопаснее).

**«Посмотреть что изменилось»** (опц. v1.0, можно отложить):
- Diff между `Document.updated_at` двух версий. Это уже отдельная фича (см. `JD-preview` в `recommendations_router.py:235`).
- v1.0: показываем только факт «обновилась», без diff.

---

## 4. RBAC

| Действие | Роли | Endpoint |
|---|---|---|
| Просмотр ДИ позиции | methodologist + admin (read-only) | `GET /v1/positions/{id}` |
| Загрузка ДИ | methodologist + admin | `POST /v1/documents` (с `category='job_instruction'`) + `PATCH /v1/positions/{id}` |
| Замена / удаление ДИ | methodologist + admin | `PATCH /v1/positions/{id}` |
| Генерация онбординг-курса | methodologist + admin | `POST /v1/ai/generate-course` (mode=`position_onboarding`) |
| Регенерация после обновления ДИ | methodologist + admin | то же |
| Просмотр баннера «ДИ обновилась» | methodologist + admin | derived |

**Студенты:** НЕ имеют доступа к ДИ напрямую (ДИ — внутренний документ для методолога). Студент видит **только сгенерированный курс**, не источник.

**Cross-tenant:** все запросы фильтруются по `user.tenant_id` через `require_tenant_user()`. Попытка прочитать чужую позицию / чужую ДИ → 404 (не 403).

---

## 5. Границы v1.0 (что НЕ делаем)

| Фича | Почему не в v1.0 |
|---|---|
| ❌ Несколько ДИ на одну позицию | Architect decision 2026-06-30 (one-to-one). v1.1 если попросят. |
| ❌ Авто-регенерация курса при изменении ДИ | Architect decision 2026-06-30 (ручной контроль через баннер). Авто-режим опасен — может сломать ongoing enrollments. |
| ❌ Diff между версиями ДИ | Отдельная фича, не блокирует epic. |
| ❌ ДИ в виде структурированного YAML/JSON (а не PDF/DOCX) | v1.0 принимает файлы как есть. AI парсит через Docling. |
| ❌ Шаблоны ДИ | v1.1 (методолог хранит свои шаблоны, новые позиции создаются из шаблона). |
| ❌ Подпись/утверждение ДИ (ЭЦП) | Compliance фича, отдельный epic. |
| ❌ Локализация ДИ | Уже работает через `documents` с `language`. |

---

## 6. Сценарии DoD (Definition of Done)

### 6.1. Главный сценарий — «загрузил ДИ → сгенерил курс → сотрудник прошёл»

1. Методолог открывает `/positions/{бухгалтер.id}`.
2. Видит вкладку «Должностные инструкции» → кнопка «📎 Загрузить ДИ» → выбирает `ДИ_Бухгалтер_v3.pdf`.
3. ДИ загружена, `Position.instruction_document_id` установлен.
4. Методолог кликает «🎓 Сгенерировать онбординг-курс» → dialog → submit.
5. Через ~2 минуты получает готовый курс с 2-3 модулями и тестами.
6. Курс автоматически привязан к позиции «Бухгалтер».
7. HR грузит штатку с 5 бухгалтерами → apply-rules → все 5 получают новый курс.
8. Один из бухгалтеров проходит курс → сертификат выдан.

**Acceptance:** все 8 шагов работают end-to-end.

### 6.2. Без ДИ → нет курса

1. Методолог открывает `/positions/{новая.id}` без ДИ.
2. Кнопка «🎓 Сгенерировать онбординг-курс» disabled.
3. Если методолог как-то доходит до API напрямую: `POST /v1/ai/generate-course { mode: "position_onboarding", position_id }` → `422 INSTRUCTION_REQUIRED` с понятным сообщением.

**Acceptance:** ни UI, ни API не дают сгенерить курс без ДИ.

### 6.3. ДИ обновилась → ручная регенерация

1. ДИ заменена (`PUT /v1/documents/{id}` или replace через UI).
2. На `/positions/{id}` появляется баннер «⚠️ ДИ обновилась».
3. На `/courses/{id}/edit` (если открыт) — badge в header.
4. Методолог решает регенерировать или нет.
5. Если регенерирует → новый курс, старый остаётся для ongoing enrollments.

**Acceptance:** авто-регенерации НЕ происходит, баннер виден.

### 6.4. Cross-tenant

1. Tenant A: методолог загружает ДИ, генерит курс.
2. Admin Tenant B пытается `GET /v1/positions/{A_position_id}` → 404.
3. Пытается `POST /v1/ai/generate-course { position_id: A_position_id }` → 404.

**Acceptance:** все запросы фильтруются по tenant_id.

### 6.5. RBAC

1. Student пытается `POST /v1/ai/generate-course { mode: "position_onboarding", ... }` → 403.
2. Student пытается `PATCH /v1/positions/{id}` с `instruction_document_id` → 403.
3. Methodologist может всё перечисленное в §4.

**Acceptance:** RBAC матрица соблюдена.

---

## 7. Известные риски

| Риск | Митигация |
|---|---|
| AI «выдумывает» контент за пределами ДИ | System prompt явно запрещает + инструмент `search_documents` отключён + post-generation проверка (citation в каждом уроке) |
| ДИ слишком короткая для `num_modules` | Pipeline редуцирует `num_modules`, не выдумывает. UI clamp до 5 |
| При замене ДИ ломаются ongoing enrollments | v1.0: additive (старый курс остаётся, новый добавляется). Отдельная replace strategy — v1.1 |
| Большая ДИ → медленная генерация | num_modules clamp 1..5. При необходимости v1.1 — streaming / progress UI |
| Ингест ДИ в pgvector требует embedding — что если Qwen упал? | Existing fallback chain (Qwen → Voyage) уже работает. ДИ идёт через тот же путь |

---

## 8. Сводная таблица реализации (заполняется после имплементации)

| Требование ТЗ | Файл | Строки | Тест |
|---|---|---|---|
| §1.1 миграция category | `alembic/versions/0041_documents_category.py` | new | `tests/test_documents_category.py` |
| §1.2 миграция Position.instruction_document_id | `alembic/versions/0042_position_instruction.py` | new | `tests/test_position_instruction_fk.py` |
| §1.3 миграция Course.source_instruction_id | `alembic/versions/0043_course_source_instruction.py` | new | `tests/test_course_source_instruction.py` |
| §2.2 schema AIGenerateRequest | `app/modules/ai/schemas.py` | new fields | `tests/test_ai_generate_position_mode.py` |
| §2.3 endpoint position_onboarding | `app/modules/ai/router.py` | new branch | same |
| §2.4 system prompt | `packages/ml-pipeline/prompts/architect/system.md` + `app/modules/ai/architect.py` | modified | manual + smoke |
| §2.5 auto-attach к позиции | `app/modules/ai/pipeline.py` | new step | same |
| §2.6 audit log | `app/modules/audit/` | new entry | `tests/test_audit_instruction_generated.py` |
| §3.1 UI загрузки ДИ | `apps/web/src/app/positions/page.tsx` (или split) | new tab | E2E Playwright |
| §3.2 UI генерации | same | new dialog | E2E |
| §3.3 UI баннера обновления | same | new banner | E2E |

---

## 9. Замечание для исполнителя (по AGENTS.md)

Этот epic затрагивает: миграции, ORM, schemas, AI pipeline, system prompt, UI. Перед началом работы обязательно загрузить skills:

| Работа | Skill |
|---|---|
| Миграция, FK, индексы | `postgres-patterns` |
| Endpoints, схемы, error envelope (особенно 422 с details) | `api-design` |
| Service/repository, тесты | `tdd-workflow` |
| Router, async service | `fastapi-patterns` |
| Query, auth, cross-tenant | `security-review` |
| AI prompt / pipeline | (нет специализированного — `fullstack-dev` общий) |
| Перед «готово» | `verification-before-completion` |

**Mandatory перед PR:**
- ≥80% coverage на новый код (AI router branch + position router patch + documents router update).
- Integration test на каждый новый endpoint.
- Cross-tenant тест (§6.4).
- RBAC тест (§6.5).
- Миграция + ORM + service + UI деплоятся **одним PR**.

---

## 10. Открытые вопросы для архитектора

_(None — все вопросы решены 2026-06-30. См. финальные решения в начале документа.)_