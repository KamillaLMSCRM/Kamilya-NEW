# P0: рабочий флоу должностной инструкции

## Цель

Реализовать минимально законченный путь методолога: сохранить исходный файл ДИ у должности, проверить извлечённые поля, запустить генерацию одного курса по этой ДИ, сохранить связь источника и показать понятное состояние в UI.

## Пункт 1 — модель данных и migration

- Добавить `Document.category` (`general` / `job_instruction`).
- Добавить `Position.instruction_document_id`.
- Добавить `Course.source_instruction_id` и `source_instruction_version_at`.
- Добавить tenant-safe indexes/FK и обновить ORM/Pydantic schemas.

**Что сделано:** миграция `0063` добавляет категорию документа, текущий источник должности, provenance курса, FK и индексы. Миграция применена к настроенной Supabase БД; `alembic current` показал `0063 (head)`.

**Статус:** completed

## Пункт 2 — хранение и API исходного файла

- Сохранять bytes документа через существующий storage backend, а не удалять единственную копию после ingestion.
- Добавить tenant-scoped download endpoint.
- Добавить upload/analyze/replace contract для ДИ должности и вернуть состояние источника в Position API.

**Что сделано:** выделен `job_instruction`, исходный бинарный файл сохраняется через storage backend, добавлены tenant-scoped download и upload/replace endpoints. `PositionResponse` возвращает файл, статус индексации и состояние связанного курса.

**Статус:** completed

## Пункт 3 — генерация одного курса по ДИ

- Добавить position endpoint, который атомарно проверяет ДИ, лимиты и отсутствие активного дубля.
- Создать один draft Course со связью с ДИ и PositionCourse.
- Запустить существующий AI pipeline в созданный `course_id` с document id.
- Списать отдельный JD trial usage, не общий бесплатный AI-курс.

**Что сделано:** endpoint создаёт один native draft, связывает его с должностью и текущим источником, запускает существующий AI pipeline в этот draft. Добавлены защита от активного дубля, повтор после failed job и отдельный JD trial counter. Конвейер исправлен так, чтобы обновлять заранее созданный курс, а не вставлять дубликат PK.

**Статус:** completed

## Пункт 4 — state-driven UX

- Переработать `/positions`: полные русские термины, источник и его статус, одно следующее действие.
- Заменить «темы → пустые черновики» прямой генерацией курса по ДИ.
- Скрыть недоставленный learner onboarding quiz.
- Добавить loading/error/success states, contextual limit и ссылки на созданный курс.

**Что сделано:** `/positions` показывает источник и индексацию, оставшийся JD-лимит, генерацию, ошибку, устаревшую версию и ссылку на draft. Основное действие зависит от состояния. Недоставленный onboarding quiz и прежнее создание пустых курсов по темам скрыты из рабочего сценария.

**Статус:** completed

## Пункт 5 — проверки и документация

- Unit/route/service tests для tenant/RBAC, source linking, idempotency и limits.
- Backend suite, frontend typecheck/tests/build.
- Обновить пользовательскую и внутреннюю документацию фактическим флоу.
- Commit/push; production deploy проверять только после попадания в master.

**Проверки:** `compileall`; 42 связанных backend-теста; 41 frontend-тест; `npm run typecheck`; production `next build`; OpenAPI 187 paths с тремя новыми маршрутами. Пользовательская и внутренняя документация обновлены.

**Статус:** completed
