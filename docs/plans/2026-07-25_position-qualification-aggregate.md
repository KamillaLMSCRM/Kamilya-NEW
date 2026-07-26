# Wave 2.2 — карточка должности как агрегат квалификации

Дата начала: 2026-07-25  
Статус: in progress  
Владелец интеграции: Codex  
Исходный план: `docs/plans/2026-07-24_methodologist-cabinet-remediation.md`, D2.

## Цель

Сделать должность канонической точкой управления квалификационными
требованиями. Методолог должен видеть и редактировать в одном контексте:

1. профиль должности;
2. должностную инструкцию;
3. компетенции;
4. обязательное обучение;
5. onboarding-тест;
6. историю изменений.

Раздел штатного расписания не должен повторно редактировать связи
`position-course`: он показывает правила только для чтения и ведёт в карточку
должности.

## Ограничения

- learning-content роль: только `methodologist`;
- каждый backend query и mutation явно ограничен `tenant_id`;
- существующие назначения и происхождение enrollment нельзя потерять;
- один тип отношения имеет один канонический редактор;
- миграции должны проходить на чистой и существующей БД;
- desktop, tablet и mobile состояния проверяются до production;
- production deploy выполняется только после зелёных CI и локальных тестов.

## Пункт 1 — инвентаризация и продуктовый контракт

1. Составить карту текущих моделей, API, страниц и тестов.
2. Найти дублирующиеся редакторы position-course, competencies и JD.
3. Зафиксировать DTO единой карточки и ownership каждой вкладки.
4. Определить, нужна ли миграция для onboarding-test и истории версий.

**Статус:** completed. Инвентаризация закреплена в aggregate DTO, каноническом route и документации ownership.

## Пункт 2 — backend aggregate

1. Добавить tenant-scoped read model карточки должности.
2. Добавить минимальные mutation endpoints для отношений, которых не хватает.
3. Сохранить существующие специализированные endpoints как совместимые
   внутренние механизмы, не создавая второй редактор в UI.
4. Добавить audit/version evidence для отображаемой истории.

**Статус:** completed. Добавлены tenant-scoped aggregate/mutations, immutable versions, restore и hooks для существующих mutation endpoints.

## Пункт 3 — frontend карточки должности

1. Ввести канонический route карточки должности.
2. Реализовать шесть вкладок с отдельными loading/error/empty states.
3. Перевести список должностей и связанные deep links на новый route.
4. Сделать штатные правила read-only с переходом в должность.
5. Не возвращать учебные функции в кабинет tenant admin.

**Статус:** completed. Реестр должностей ведёт в каноническую карточку; дублирующие редакторы заменены read-only связями и deep links.

## Пункт 4 — тесты и UX QA

1. Backend integration tests: read aggregate, mutations, tenant isolation,
   missing position, role policy.
2. Frontend tests: вкладки, ошибки, пустые состояния, read-only redirect.
3. TypeScript, Vitest, Ruff, compileall и полный backend suite.
4. Playwright: desktop `1440x900`, tablet `820x1180`, mobile `390x844`.

**Статус:** completed. Автоматические проверки и browser QA на desktop/tablet/mobile зелёные.

## Пункт 5 — документация и production

1. Обновить внутреннюю документацию и руководство методолога.
2. Провести migration dry run локально.
3. Commit/push с автором `kamilla_lms_crm@proton.me`.
4. Дождаться GitHub CI и Vercel, затем развернуть Render/worker при наличии
   backend изменений.
5. Проверить production revision и основной пользовательский flow.

**Статус:** in progress. Документация и migration dry run завершены; commit, deploy и production verification ожидают browser QA.

## Результаты локальной проверки

- Alembic: `0073 -> 0072 -> 0073 (head)` — успешно.
- Backend focused: 20 тестов — успешно.
- Backend full suite: 506 тестов — успешно.
- Frontend Vitest: 138 тестов — успешно.
- TypeScript: `tsc --noEmit` — успешно.
- Next.js production build: успешно; остаются существующие предупреждения lint вне текущего scope.
- Browser QA: desktop `1440x900`, tablet `820x1180`, mobile `390x844` — успешно; body overflow отсутствует, вкладки имеют изолированный horizontal scroll.
- Production revision: pending.
