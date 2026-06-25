# Positions: Bulk-JD + AI Recommendations — handoff

**Branch:** `feature/positions-bulk-ai`
**Author of changes:** Mavis (auto-deployed since you were away)
**Status:** Backend + frontend working, ready for your review
**Not merged to master** — push is in feature branch only.

---

## Что сделано

### 1. Bulk-JD upload (несколько JD файлов разом)

**Backend** — `apps/api/app/modules/positions/`
- `POST /api/v1/positions/bulk-analyze-jd` — multipart с `files: List[UploadFile]`, max 50 файлов
  - Возвращает `BulkJDResponse{items: [{filename, name, department, level, responsibilities, requirements, error}]}`
  - Per-file failures НЕ валят весь запрос — каждая ошибка в `error` поле
- `POST /api/v1/positions/bulk-create` — `{items: [{name, department, level, responsibilities, requirements, course_ids}]}`, max 200
  - Возвращает `BulkPositionResponse{created, failed}`
  - Каждая позиция в savepoint, ошибка одной не откатывает другие
  - Tenant-scoped (берёт `user.tenant_id`)

**Frontend** — `apps/web/src/app/positions/page.tsx`
- Новая кнопка «Массовая загрузка JD» в toolbar (синяя, primary/5 background)
- Multi-file input (`.pdf,.docx,.doc,.txt`)
- Модалка превью с чекбоксами, отметка файлов с ошибками, кнопка «Создать N должностей»
- В toast'е: «Проанализировано: N успешно, M с ошибками»

### 2. AI-рекомендации контента по ДИ

**Backend** — `apps/api/app/modules/positions/router.py`
- `GET /api/v1/positions/{position_id}/recommended-content?limit=5` (limit 1..20)
- Берёт `responsibilities + requirements`, embedding через Qwen (с hash fallback), cosine search в `document_embeddings` (tenant-scoped)
- Over-fetch 5x для dedup по `doc_id`, возвращает top-N unique documents с `similarity` (0..1)
- Returns: `RecommendedContentResponse{items: [{doc_id, doc_name, similarity, headings}]}`

**Frontend** — `apps/web/src/app/positions/page.tsx`
- Кнопка «Подобрать курсы» в карточке position (primary/5 background)
- Inline panel с процентом similarity для каждого рекомендованного документа
- Кнопка переключается на «Скрыть» когда открыто

---

## Дизайн-решения

1. **Per-file error handling, не fail-fast.** Если 1 из 20 JD не распарсился — остальные 19 создаются, ошибка в `error` поле.
2. **Per-position savepoint в bulk-create.** Если item #5 валится, items #1-4 и #6+ сохраняются.
3. **Over-fetch в vector search.** Top 25 chunks → dedupe по doc_id → top 5 unique. Один документ не занимает 5 мест.
4. **`similarity` не `distance`.** 0..1, где 1 = identical. Проще UI ("95% похоже").
5. **Tenant isolation везде.** `WHERE tenant_id = :tenant_id` в SQL, `pos.tenant_id != user.tenant_id → 404` в recommended.
6. **`recommended-content`, не `recommended-courses`.** `document_embeddings` — единица чанка, не курса. Курс строится поверх документов (architect.py). Методолог видит документы и сам решает, какие курсы (на базе этих документов) привязать. Если хочешь прямую привязку к `courses.id` — отдельная задача, нужна агрегация embeddings по course_id.

---

## Что НЕ сделано (out of scope, по согласованию)

- **AI-генерация ДИ по названию** (без файла, по 2-3 словам) — отложено
- **Превью/дифф после анализа** (показать что AI поменял в полях) — отложено
- **Версионирование ДИ** — отложено
- **Прямая привязка рекомендаций к курсам** (сейчас → документы) — отдельный PR
- **i18n для новых строк** (тексты в UI на русском) — можно потом, через `t()` после стабилизации копий
- **Кеширование embeddings для position** — каждый вызов recomputes. Если будет медленно — добавим cache в `Position.description_embedding`

---

## Что проверить когда вернёшься

1. **Review diff:**
   ```bash
   cd D:\Камиля\lms
   git fetch origin
   git diff origin/master..feature/positions-bulk-ai
   ```
2. **Smoke test на staging** (если есть):
   - Зайти в `/positions`
   - Нажать «Массовая загрузка JD» → выбрать 3-5 PDF/DOCX
   - Должна открыться модалка с превью
   - Нажать «Создать N должностей» → toast с результатом
   - Открыть любую должность → «Подобрать курсы» → должны появиться похожие документы
3. **Если ок — merge:**
   ```bash
   gh pr create --base master --head feature/positions-bulk-ai --title "feat(positions): bulk-JD upload + AI content recommendations"
   # или merge напрямую:
   git checkout master
   git merge --no-ff feature/positions-bulk-ai
   git push origin master
   ```
4. **Если что-то не так** — скажи, поправлю

---

## Файлы изменены

| Файл | Изменение |
|---|---|
| `apps/api/app/modules/positions/schemas.py` | +8 новых Pydantic моделей |
| `apps/api/app/modules/positions/router.py` | +3 endpoint, +импорты |
| `apps/web/src/app/positions/page.tsx` | +bulk upload UI, +recommend panel, +handlers, +state |

**Без изменений:** models.py, миграции (не нужны), конфиг, env vars.

---

## Known follow-ups (не блокеры)

- `pyproject.toml` имеет `strict = true` mypy, но нет pydantic plugin → mypy ругается на все pydantic schemas (pre-existing). Лучше добавить plugin в отдельном PR.
- Bulk-create max 200 позиций за раз — для крупного onbording (500+ должностей) может быть мало. Поднять или сделать пагинацию — отдельная задача.
- В рекомендациях similarity вычисляется по `responsibilities + requirements` склеенным через `\n`. Если одно из полей пустое — другой всё равно работает. Но edge case: position без обоих полей → пустой результат (обработано, возвращаем `items: []`).
