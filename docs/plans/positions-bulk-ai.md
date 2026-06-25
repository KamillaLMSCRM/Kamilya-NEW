# Positions: Bulk-JD + AI + Versions + Audit + Course Suggestions — handoff (round 4)

**Branch:** `feature/positions-bulk-ai`
**Status:** Round 4 (course suggestions) + all prior rounds ready for review
**Not pushed to master** — push is in feature branch only.

- Round 1 (pushed): bulk-JD upload, recommended-content, mypy plugin prep
- Round 2 (pushed): generate-from-name, JD preview/diff, JD versioning, recommended-courses
- Round 3 (pushed): AI-аудит ДИ (качество, compliance)
- **Round 4 (this commit): AI-suggest курсов из ДИ — методолог выбирает, мы создаём draft + привязываем к position**

---

## Round 4: AI course suggestions (Phase 2)

**Сценарий:** методолог нажимает «💡 Предложить курсы» на сохранённой position → AI анализирует ДИ (responsibilities + requirements) → возвращает 3-5 тем с описанием и обоснованием → методолог выбирает какие → мы создаём draft courses (status='draft') и автоматически привязываем к position (через `position_courses`). Контент курса пустой — методолог наполняет через существующий `/ai/generate/`.

### Backend
- `POST /api/v1/positions/{id}/suggest-courses` — LLM предлагает 3-5 тем
  - Возвращает `[{title, description, estimated_chapters, reason}]`
  - Темы конкретные, не общие («Введение в компанию» → «Работа с CRM: основные сценарии для кассира»)
  - Best-effort: ошибка AI → `items: []`
- `POST /api/v1/positions/{id}/create-courses` — создаёт draft courses + привязка
  - Body: `{items: [{title, description}]}` (max 10)
  - Возвращает `[{id, title}]` + `attached_to_position: N`
  - Tenant-scoped, использует user.tenant_id
  - `ai_generated: false` (потому что мы только title/description, не content)

### Frontend
- Кнопка `💡 Предложить курсы` в карточке position (emerald-цвет, рядом с `🔍 AI-аудит`)
- Модалка со списком suggestions
  - Каждый item — чекбокс + title + description + estimated chapters badge + reason
  - Auto-select all по умолчанию (методолог снимает ненужные)
- Кнопка `Создать N черновиков`
- Toast: «Создано N черновиков курсов. Наполните контент через «Генерация курсов»»
- После создания — `fetchPositions()` чтобы badge «N курсов» в карточке обновился

### Удалён дубль
- В router.py был **двойной** `restore_jd_version` (старый URL `/restore-jd/{version_id}` и новый `/jd-versions/{version_id}/restore`). Оставил только новый.

---

## Новые файлы / изменения (round 4)

| Файл | Изменение |
|---|---|
| `apps/api/app/modules/positions/schemas.py` | +`CourseSuggestion` + `CourseSuggestionsResponse` + `CreateCourseItem` + `CreateCoursesRequest` + `CreatedCourseRef` + `CreateCoursesResponse` |
| `apps/api/app/modules/positions/router.py` | +`suggest_courses()`; +`create_courses_from_suggestions()`; import `Course` model; удалён дубль `restore_jd_version` |
| `apps/web/src/app/positions/page.tsx` | +`CourseSuggestion` interface; +suggestions state; +`handleSuggestCourses`; +`handleCreateCoursesFromSuggestions`; +кнопка `💡 Предложить курсы` в карточке; +модалка suggestions |

**Без изменений:** models, migrations, schemas core, course generation pipeline (используется существующий).

---

## Verified

- ✅ `pnpm typecheck` (frontend) — clean
- ✅ FastAPI app — **21 unique** position routes, **0 duplicates**
- ✅ Imports clean (schemas, router, app)

---

## Все rounds вместе — endpoint map

### Round 1 (bulk-JD + recommendations)
- `POST /analyze-jd` (+ audit из round 3)
- `POST /bulk-analyze-jd` (+ audit из round 3)
- `POST /bulk-create`
- `GET /{id}/recommended-content`

### Round 2 (versions + courses + generate)
- `POST /generate-jd-from-name` (deprecated by user, оставлен)
- `POST /{id}/jd-preview` (diff against current)
- `GET /{id}/recommended-courses`
- `GET /{id}/jd-versions`
- `POST /{id}/jd-versions` (manual snapshot)
- `POST /{id}/jd-versions/{version_id}/restore`
- Auto-snapshot on PUT (встроен в update_position)

### Round 3 (audit)
- `POST /{id}/jd-audit` (re-audit without file)

### Round 4 (course suggestions)
- `POST /{id}/suggest-courses` ← **new**
- `POST /{id}/create-courses` ← **new**

---

## Что осталось (deferred, отдельные PR)

- **Phase 3: AI-generate onboarding quiz из ДИ** — последняя фаза из трёх
  - Из responsibilities+requirements получить 5-10 questions
  - Методолог одобряет/правит
  - Quiz сохраняется в position, автоназначается при onboarding
  - Прохождение квиза = подтверждение что сотрудник понял ДИ

- **Pre-existing:** mypy errors в `app/core/config.py` и `db.py`
- **Phase 2 (this round) limitation:** созданные курсы — drafts без контента. Методолог должен отдельно зайти в `/ai/generate/` чтобы наполнить контентом. Это **намеренно** — следующая фаза (или ручной workflow) — генерация полного контента в один клик.

---

## Рекомендация по merge

**Merge `feature/positions-bulk-ai` в master одним PR.** Squashed или merge commit — на твоё усмотрение.

После merge:
- Применить `alembic upgrade head` (для 0022)
- Vercel auto-deploy для frontend
- Render auto-deploy для backend

## Caveats (финальные)

1. Migration `0022` НЕ применена автоматически — нужно `alembic upgrade head` вручную
2. Нет unit-тестов на новые endpoint (4 rounds, 13+ новых endpoints без тестов)
3. Phase 3 (quiz generation) — отдельный PR
4. Real-time: AI calls синхронные, могут быть 3-10 сек на запрос (suggest-courses, jd-audit) — UX с loading spinner есть
5. **Созданные draft courses без контента** — UX может быть confusing если методолог забудет наполнить. Можно добавить badge "черновик" + warning в courses list — отдельная задача


## Round 2: what changed

### 1. AI-генерация ДИ по названию (без файла)

**Backend** — `POST /api/v1/positions/generate-jd-from-name`
- Body: `{name, department?, level?}`
- LLM генерирует responsibilities + requirements + уточняет name/department/level
- Same LLM prompt family as analyze-jd, just no text extraction

**Frontend** — кнопка `✨ Сгенерировать` рядом с input названия (в форме создания)
- Disabled пока name пустое
- Показывает toast «AI сгенерировал ДИ. Проверьте и отредактируйте.»

### 2. Превью/дифф после анализа

**Backend** — `POST /api/v1/positions/{id}/jd-preview`
- Body: `{text, name?, department?, level?}` (text — содержимое JD)
- LLM сравнивает current position vs AI предложение
- Возвращает `[{field, current, proposed, changed}]` — 5 полей

**Frontend** — модалка диффа открывается когда:
- Пользователь **edit** существующей position
- И загружает JD-файл через "Загрузить JD"
- Вместо silent overwrite → preview модалка "AI предложил изменения"
- Side-by-side сравнение (Было / Станет) для каждого измененного поля
- Кнопки "Отклонить" / "Применить изменения"
- **Без изменений** → silent fill (старое поведение, не ломаем)

### 3. Версионирование ДИ

**Backend** — новая таблица `position_jd_versions`:
```
id, position_id, tenant_id, responsibilities, requirements,
created_by, source ('auto' | 'manual'), note, created_at
```

**Endpoints:**
- `GET  /api/v1/positions/{id}/jd-versions` — список (newest first)
- `POST /api/v1/positions/{id}/jd-versions` — manual snapshot с note
- `POST /api/v1/positions/{id}/jd-versions/{version_id}/restore` — восстановить
- **Auto-snapshot** в существующем `PUT /api/v1/positions/{id}`: если responsibilities или requirements меняются, перед update создаётся auto-snapshot старых значений

**Frontend:**
- Кнопка `История` в карточке position
- Модалка со списком снимков (timestamp, source badge, note, кнопка "Восстановить")
- Кнопка "📌 Снять снимок сейчас" в модалке (для маркировки known-good состояний)

**Migration:** `0022_add_position_jd_versions.py` (НЕ применена автоматически — запусти вручную):
```bash
cd apps/api
alembic upgrade head
```

### 4. Прямая привязка рекомендаций к курсам

**Backend** — `GET /api/v1/positions/{id}/recommended-courses?limit=5`
- Та же vector search в `document_embeddings` (как `recommended-content`)
- **Но** дополнительно: для каждого top doc_name проверяем fuzzy-match с `course.title`:
  - Exact match (case-insensitive)
  - Substring match в любую сторону
- Возвращает `[{course_id, title, similarity, matched_doc_name}]`
- **Heuristic** (нет formal document→course mapping в БД). Proper агрегация потребует новой таблицы `course_documents` — отдельный PR.

**Frontend:**
- В recommendations panel теперь **две секции**: "Документы" + "Курсы"
- Кнопка "Подобрать курсы" загружает оба параллельно (Promise.all)
- Если courses пуст → "Не нашлось курсов с похожим контентом"

### 5. mypy fix (pre-existing)

**pyproject.toml** — добавлен `pydantic.mypy` plugin:
```toml
[tool.mypy]
plugins = ["pydantic.mypy"]
```

**Что фиксит:** mypy больше не ругается на `BaseModel cannot subclass`. Все pydantic schemas в `positions/schemas.py` теперь проходят mypy clean.

**Что НЕ фиксит:** pre-existing errors в `app/core/config.py` (no type annotations) и `app/core/db.py` (async generator return type). Эти не мои, отдельная задача.

---

## Новые файлы / изменения

| Файл | Изменение |
|---|---|
| `apps/api/alembic/versions/0022_add_position_jd_versions.py` | **NEW** — migration для versions table |
| `apps/api/app/modules/positions/models.py` | +`PositionJDVersion` model |
| `apps/api/app/modules/positions/schemas.py` | +7 новых schemas (GenerateJD, JDPreview, RecommendedCourses, JDVersion×3, JDRestore) |
| `apps/api/app/modules/positions/router.py` | +6 endpoints + auto-snapshot в PUT |
| `apps/web/src/app/positions/page.tsx` | +3 interfaces, +5 state, +6 handlers, +3 модалки (preview/history/refactor recommendations) |
| `apps/api/pyproject.toml` | +`pydantic.mypy` plugin |

**Без изменений:** documents/ courses/ ai/ routers (только positions).

---

## Type-check & smoke test

- `pnpm typecheck` (frontend) — **clean** ✅
- `mypy app/modules/positions/` — clean для **моих** файлов; 4 pre-existing errors в `core/config.py` и `core/db.py` (не мои)
- FastAPI app imports — clean, 21 endpoint зарегистрированы (10 ранее + 11 новых) ✅
- Migration file syntax — valid, нужен `alembic upgrade head` для применения

---

## Что нужно сделать когда вернёшься

1. **Apply migration:**
   ```bash
   cd D:\Камиля\lms\apps\api
   alembic upgrade head
   ```
2. **Проверить в `/positions`:**
   - Кнопка `✨ Сгенерировать` рядом с input названия
   - Edit существующей position → Загрузить JD → preview modal
   - Кнопка `История` → модалка со снимками
   - Кнопка `Подобрать курсы` → две секции (документы + курсы)
3. **Если ок — merge feature branch в master:**
   ```bash
   git checkout master
   git merge --no-ff feature/positions-bulk-ai
   git push origin master
   ```
4. **Создать PR:** https://github.com/KamillaLMSCRM/Kamilya-NEW/pull/new/feature/positions-bulk-ai

---

## Известные limitations (для v1.1+)

1. **Recommended-courses использует fuzzy match по `course.title`** — не точное сопоставление с `document`. Если у тебя 50 курсов и 200 документов с похожими названиями, рекомендации могут быть странными. **Нужна таблица `course_documents` для proper mapping** — отдельный PR.

2. **Auto-snapshot только для responsibilities/requirements.** Поля name/department/level не версионируются (они обычно не меняются часто, и audit log покрывает их).

3. **Migration НЕ применена автоматически.** Только файл. Нужно `alembic upgrade head` вручную (или через Render deploy hook).

4. **Heuristic dedup by doc_name.** В `recommended-content` мы делаем vector search и dedup по `doc_id`. Но в `recommended-courses` мы дополнительно делаем fuzzy match по `doc_name ↔ course.title`. Это может дать дубликаты, если 2 курса имеют похожие названия.

5. **Нет тестов.** Эта фича добавлена без unit-тестов. Для production рекомендую добавить:
   - `tests/test_positions_bulk.py` (уже есть аналогичный для существующего функционала)
   - `tests/test_positions_versions.py`
   - UI тесты через vitest + React Testing Library

---

## План v1.1 (если пользователь доволен)

- Таблица `course_documents` для proper doc↔course mapping
- UI для version diff (visual side-by-side)
- Экспорт/импорт versions в JSON
- Auto-cleanup (старые auto-snapshots через N дней)
- i18n строк (сейчас hardcoded RU)
- Real-time: WebSocket notification когда AI auto-snapshot создан
