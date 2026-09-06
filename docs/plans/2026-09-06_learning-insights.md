# Learning insights implementation

## План для владельца продукта

Цель: методист видит не только итоговый балл, но и конкретные ошибки сотрудника,
повторяющиеся затруднения коллектива и изменение результата после пересдачи.
Это инструмент принятия решения, а не автоматический вывод «сотрудник плохой»
или «курс неправильный».

### 1. Разбор конкретного сотрудника

- В существующем журнале обучения — действие «Разбор ответов» для обычного курса.
- Показать дату, тест, редакцию, номер попытки и результат.
- У каждого вопроса: формулировку на момент сдачи, выбранные варианты, правильные
  варианты по ключу теста, баллы и сохранённое объяснение.
- Предоставить переход в редактор курса, если соответствующий материал определён.
- Старые попытки без сохранённого подтверждения показать как недоступные для
  разбора; не восстанавливать их из текущей версии курса.

Приёмка: выбранный сотрудник и попытка совпадают с назначением; исправление
курса не меняет исторический разбор; чужая компания и неподходящая роль не имеют доступа.

### 2. Общие пробелы по курсу

- Выбрать курс независимо от текущей страницы журнала; сузить выборку подразделением,
  должностью и периодом. Даты трактуются как календарные дни Казахстана, UTC+05:00.
- Вопросы с наибольшей долей ошибок — выше в списке. Рядом абсолютное число
  сотрудников и размер выборки, часто выбираемые ошибочные варианты.
- Первая завершённая попытка фиксирует исходный результат. Последняя завершённая
  попытка в пределах верхней даты показывает динамику. Один человек не превращается
  в нескольких из-за пересдач. Редакции тестов не смешиваются.
- Несопоставимая/повреждённая последняя попытка — отдельное «нет данных», а не 0% ошибок.
- При выборке меньше пяти человек предупредить о недостатке наблюдений.

Приёмка: первый неверный и последний верный ответ одного человека дают одного
респондента и одно улучшение; неизвестные ответы не улучшают показатели.

### 3. Решение методиста

- Общая отметка для конкретной редакции вопроса: «Не разобрано», «Обучить
  сотрудников», «Проверить вопрос», «Улучшить материал», «Решено».
- Сохранение с подтверждением сервера; повторная отправка не создаёт дубль.
- Одинаковый вопрос в разных открытых попытках показывает согласованную отметку.
- Массовая ошибка — повод проверить и обучение, и сам вопрос; вывод принимает человек.

В первой версии отметка относится к вопросу курса, не является персональным
поручением. Автоматическое дообучение, письма, задачи с ответственным и дедлайном,
текстовые комментарии и рейтинг сотрудников в этот выпуск не входят.

### 4. Надёжность и проверка

- Отдельная ветка/worktree от опубликованного master; прежняя рабочая копия не меняется.
- Ограниченные бюджетные агенты: backend и frontend; независимый критик проверяет
  контракт, права, достоверность статистики и состояния интерфейса.
- Новая таблица отметок с обязательной tenant-изоляцией. Оригинальные ответы — read-only.
- Миграция вперёд/назад/повторно и API/RLS-тесты на синтетических данных в одноразовой
  схеме Supabase DEV; проверенное удаление только этой схемы. Локальный Docker PG не нужен.
- Unit/контрактные тесты, регрессия журнала, TypeScript, затронутый AI-course journey,
  проверка зависимостей Graphify и итогового diff.

### 5. Отдельный выпуск

После исправления замечаний — пользовательский smoke кабинета методиста, точный
релизный SHA, CI, backup/rollback и migration gate. Сначала API с миграцией, затем
интерфейс. Производственный readback обязателен. Текущая реализация сама по себе
не означает публикацию и не разрешает изменение инфраструктуры или тарифов.

## Технический статус

Contract: ../product/learning-insights/EPIC_V1.md. Branch feat/learning-insights-20260906, base 5c297eb99c64834aac3f5b57628d017a1006f644; isolated worktree. Primary dirty checkout preserved.

- [x] Graphify QuizAttempt navigation and immutable snapshot source inspection.
- [x] Detailed API/UI contract, deduplication policy, ownership, negative space.
- [x] Backend reporting, evidence validation and annotation service.
- [x] Root additive migration/model, route registration and DB isolation test.
- [x] Journal answer inspection, course gaps and triage UI.
- [x] Independent review, focused/unit/contract tests, frontend typecheck and regression.
- [x] Synthetic Supabase DEV integration/RLS/migration checks; AI-COURSE-01 required tests.
- [x] Graph update, final diff and canonical documentation.

Production publication is not claimed by implementation completion. Fresh release preparation required for additive migration and exact candidate.

Итог первой реализации: [проверки и ограничения](../product/learning-insights/VERIFICATION_2026-09-06.md).
Frontend: 535/535; backend regression: 35/35; Python quality baseline и TypeScript:
PASS; финальная Supabase DEV проверка: все 14 групп PASS, cleanup подтверждён.
Следующий этап — браузерная приёмка под синтетическим методистом и отдельный выпуск.

## Release continuation — 2026-09-06

Mode: epic-update. Root: 01a06a58-0259-7090-9dcd-7cda95a6e036.
OWNER-CONFIRMED: proceed with the quoted browser acceptance, separate API/0155
then frontend release; narrowly correct Next.js 14 to verified 15.5.23.
No permission to change billing, reset credentials, use customer data, or weaken gates.

| Node | Owner / writer | State | Dependency and exit gate |
|---|---|---|---|
| LI-DOC | Luna / root reviewer | DONE | Exact package version and one-line diff verified |
| LI-LOCAL | Test & Evidence Runner | DONE | R1 accepted:535 web/35 API, build62 pages, typecheck, quality and release-contract gates |
| LI-PACKAGE | root | IN_PROGRESS | Separate API-first and frontend source packages, exact SHA |
| LI-DEV | Release Runner, then Test Runner | NOT_STARTED | Exact DEV target, migration0155, synthetic browser answer/status flow |
| LI-BACKUP | root approval, Release Runner execution | NOT_STARTED | New exact temporary CT125 restore DB approval requested; signed restore and cleanup |
| LI-KZ-API | Release Runner / root acceptance | NOT_STARTED | CI/image, backup/rollback, exact0154-to0155 packet, API/all-worker/DB readback |
| LI-KZ-UI | Release Runner / Test Runner acceptance | NOT_STARTED | API accepted first, exact frontend SHA, synthetic browser and cleanup |

GIT-DERIVED: canonical project-token remote readback confirms master
5c297eb99c64834aac3f5b57628d017a1006f644 and dev
676fee152b5b052aabbacedc27d624b5987f295b. Feature checkout remains based on actual
remote master; the primary checkout has divergent historical local commits and
108 pre-existing dirty entries, none belongs in this feature package.

Production and DEV runtime identity still require fresh provider readback.
The dev hostname does not establish data isolation; next.config.js intentionally
pins the named Vercel DEV project to Render. Do not repeat the prior KZ binding
experiment. The permanent Test Runner owns only the exact worktree ledger append;
root owns plan/verification, package creation, approvals and final acceptance.
No source/test edits while LI-LOCAL checks its candidate hashes.

LI-LOCAL correction: frontend535 tests/build62 pages/typecheck and backend35
regressions passed with unchanged19-file source manifest. First quality attempt
failed before analysis because root's provided root .venv has no Ruff/mypy; the
documented primary apps/api/.venv was then independently probed (Ruff0.8.6,
mypy1.20.2) and explicitly assigned for quality only. A worker's initial Poetry
fallback also created an unintended empty worktree virtualenv; root reviews its
exact path for cleanup, with no installs authorized. Release-contract gate caught
the candidate's ERRORS header date lagging its newly added TEST-011 entry; root
corrected it to2026-09-06. Runner R1 repeats only the two failed gates.

R1 completed successfully and root accepted it. Ledger ownership returned to root.
Backend package created as local commit `a45a82a3` (no frontend source changes).
Frontend and documentation follow separately. No remote push or deployment yet.
Temporary Poetry environment cleanup was rejected by tool policy before execution;
it remains as documented bootstrap-only residue, not used by tests or release.
