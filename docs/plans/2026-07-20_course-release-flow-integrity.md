# P0: целостность публикации и назначений курсов

## Цель

Сделать публикацию единственной границей доступности курса: обучающийся не
видит и не открывает draft, назначения не активируются до публикации, а курс по
ДИ корректно заменяет активное правило должности и назначается текущим
сотрудникам без потери истории.

## Пункт 1 — зафиксировать release policy тестами

- Добавить backend-тесты для запрета ручного назначения draft.
- Добавить тесты learner dashboard: показываются только опубликованные курсы.
- Добавить тесты student course access: нужен published + enrollment.
- Добавить тесты публикации AI-курса и активации position rules.
- Добавить тест, что pipeline не записывает methodologist как learner.

**Статус:** completed

## Пункт 2 — серверная граница публикации

- Проверять status курса в manual enrollment service.
- Фильтровать learner dashboard по `Course.status=published`.
- Ограничить student-доступ к course/structure/lesson flow действующим
  enrollment опубликованного курса; methodologist/teacher сохраняют authoring
  access.
- Для AI-generated course требовать `review_status=approved` перед publish.

**Статус:** completed

## Пункт 3 — активация курса по должности

- На publish определять связи PositionCourse для курса.
- Для нового курса по ДИ деактивировать старые source-linked PositionCourse той
  же должности до recompute.
- Выполнить recompute текущих holders после публикации.
- Не удалять completed/in-progress историю старого курса.
- Rule kernel должен игнорировать draft courses.

**Статус:** completed

## Пункт 4 — убрать ошибочную запись автора

- Удалить production auto-enrollment автора standalone AI generation.
- Не менять preview/review authoring flow.

**Статус:** completed

## Пункт 5 — UX review/publish в редакторе

- Показать review status и происхождение курса.
- Добавить действия «Одобрить» и «Опубликовать» в редактор.
- Для курса по ДИ объяснить, что публикация активирует назначение по должности.
- Не предлагать «Назначить» до успешной публикации.

**Статус:** completed

## Пункт 6 — проверка и документация

- Запустить связанные backend tests, frontend typecheck/tests/build.
- Обновить фактическую внутреннюю и пользовательскую документацию.
- Зафиксировать результаты и известные ограничения в этом плане.

**Статус:** completed

## Результат проверки

- Backend DB-independent tests: `89 passed`.
- Frontend tests: `41 passed`.
- Frontend typecheck: passed.
- Next.js production build: passed; остались только существующие lint warnings вне изменённого flow.
- RBAC integration suite: `10` тестов не запущены, потому что fixture ожидает локальный PostgreSQL на `localhost:5432`; общая Supabase БД намеренно не использовалась для пишущих integration-тестов.

**Итоговый статус:** completed
