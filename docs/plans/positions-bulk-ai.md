# Positions: Bulk-JD + AI + Versions — handoff (round 2)

**Branch:** `feature/positions-bulk-ai` (same as round 1)
**Status:** Round 2 ready for review
**Not pushed to master** — push is in feature branch only.

Round 1 (already pushed): bulk-JD upload, recommended-content, mypy plugin prep.
Round 2 (this commit): generate-from-name, JD preview/diff, JD versioning, recommended-courses.

---

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
