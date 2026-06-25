# Positions: Bulk-JD + AI + Versions + Audit — handoff (round 3)

**Branch:** `feature/positions-bulk-ai`
**Status:** Round 3 ready for review (final planned phase)
**Not pushed to master** — push is in feature branch only.

- Round 1 (pushed): bulk-JD upload, recommended-content, mypy plugin prep
- Round 2 (pushed): generate-from-name, JD preview/diff, JD versioning, recommended-courses
- **Round 3 (this commit): AI-аудит ДИ — то, что пользователь имел в виду с самого начала**

---

## Round 3: AI-аудит ДИ (the real ask)

**Пользовательский сценарий:** HR загружает ДИ для позиции → AI анализирует, подсвечивает замечания → методолог правит ДИ на основе замечаний → потом генерирует курсы и тесты для онбординга.

### Backend
- `_audit_jd_text()` — приватная функция с structured LLM prompt
  - Категории: completeness / specificity / clarity / compliance / structure / other
  - Severity: warning / suggestion / ok
  - Возвращает 3-7 findings (положительные тоже, severity=ok)
  - Best-effort: при ошибке AI возвращает `[]`, не блокирует основной analyze-jd
- `POST /api/v1/positions/analyze-jd` — теперь возвращает `issues: [JDAuditItem]` вместе с парсингом
- `POST /api/v1/positions/bulk-analyze-jd` — каждая item содержит `issues: [JDAuditItem]`
- `POST /api/v1/positions/{id}/jd-audit` — **новый**: re-audit сохранённой позиции без файла
  - Использует `responsibilities + requirements` как вход
  - Полезно когда ДИ уже создана, и методолог хочет проверить её качество

### Frontend
- `JDAuditList` — переиспользуемый компонент (severity-цветные бейджи, с suggestion под каждым finding)
- **Preview modal** (после analyze-jd) — теперь показывает issues вверху как "AI заметил 3 замечания"
- **Bulk preview modal** — каждая item имеет бейдж `🔍 N` (количество issues), expandable details показывает issues
- **Audit modal** — отдельная модалка для кнопки `🔍 AI-аудит` в карточке position
- **Toast в bulk** — теперь сообщает "AI нашёл N замечаний и M предложений"

### Категории проверок (что AI ищет)
- **completeness** — есть ли обязанности, требования, KPI, взаимодействие с другими отделами
- **specificity** — обязанности измеримы? (не "выполняет задачи", а "обрабатывает 50 заявок/день")
- **compliance** — для производства: ОТ/ТБ, для IT: ИБ, для финансов: ПОД/ФТ
- **clarity** — нет устаревших формулировок, двусмысленностей
- **structure** — порядок и формат

### Phase 2 / Phase 3 (deferred, отдельные PR)
- **Phase 2:** AI-suggest courses from JD → используя существующий `ai/generate/` pipeline
- **Phase 3:** AI-generate onboarding quiz на основе ДИ

Пользователь сказал "пусть будет как опция" про `generate-from-name` (round 2). Оставляем deprecated, не выпиливаем.

---

## Новые файлы / изменения (round 3)

| Файл | Изменение |
|---|---|
| `apps/api/app/modules/positions/schemas.py` | +`JDAuditItem` + `JDAuditResponse`; `BulkJDItem.issues` field |
| `apps/api/app/modules/positions/router.py` | +`_audit_jd_text()`; +`POST /{id}/jd-audit`; `analyze_jd` + `bulk_analyze_jd` теперь вызывают audit |
| `apps/web/src/app/positions/page.tsx` | +`JDAuditList` component; +`auditFor/auditIssues/auditLoading` state; +`handleAudit`; +`pendingIssues` state; кнопка `🔍 AI-аудит` в карточке; issues в preview modal; бейджи в bulk modal |

**Без изменений:** все round 1-2 фичи, schemas, models, migrations.

---

## Verified

- ✅ `pnpm typecheck` (frontend) — clean
- ✅ FastAPI app — 18+ endpoint зарегистрированы, импорт без ошибок
- ✅ mypy schemas — clean (pre-existing errors в `core/*` не мои)

---

## Что НЕ сделано (phase 2/3, deferred)

- **AI-suggest courses from JD** — пользователь говорит про это явно ("генерил курсы и тестирование"), но **отдельный PR** после того как phase 1 (audit) в проде. Логика:
  - Из JD получить список тем для курсов
  - Методолог выбирает какие генерировать
  - Переиспользовать `ai/generate/` pipeline (architect + writer)
  - Курсы привязываются к position
- **AI-generate onboarding quiz** — отдельный PR. Логика:
  - Из responsibilities+requirements получить 5-10 вопросов
  - Методолог одобряет/правит
  - Quiz сохраняется в position, автоназначается при onboarding

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
