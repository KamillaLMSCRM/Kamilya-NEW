# План реализации управленческого контура обучения

Дата: 2026-09-05.

Связанные документы:

- `docs/PRODUCT_PAIN_CAPABILITY_MATRIX.md`;
- `docs/product/manager-attention/EPIC_V1.md`;
- `docs/product/manager-attention/modules/training-deadline-read-model_V1.md`;
- `docs/product/manager-attention/modules/training-deadline-read-model_V1_review-addendum.md`;
- `docs/adr/0019-recurring-learning-cycles.md`;
- `docs/adr/0021-course-assignment-notification-outbox.md`.

## Целевой результат

Перевести Kamilya от учета прохождения к управляемому циклу:

```text
назначение
  -> срок
  -> выявленная проблема
  -> действие руководителя
  -> повторное обучение
  -> измеримый результат
```

## Принципы реализации

1. Один канонический read model — журнал обучения, без нового дублирующего
   отчета.
2. Сначала наблюдаемая проблема, затем действие; автоматическую отправку нельзя
   добавлять раньше честного статуса и истории.
3. Completion, deadline, evidence и test attempt остаются привязаны к точному
   enrollment instance.
4. Все новые записи tenant-scoped, с RLS/FORCE RLS, runtime без BYPASSRLS и
   cross-tenant тестами.
5. Агрегаты слабых тем не раскрывают персональные ответы коллег и не строятся
   для слишком малой группы.
6. Каждый этап выпускается отдельным вертикальным срезом и может быть отключен
   без потери истории обучения.

## Этап 1. Единый deadline read model — VERIFIED LOCALLY + SUPABASE DEV

Результат:

- журнал связывает enrollment с course-cycle или learning-path cycle;
- показывает дату цикла, срок и статусы `active`, `overdue`,
  `completed_on_time`, `completed_late`;
- фильтр `overdue` использует только реальные immutable cycle deadlines;
- summary показывает просрочку как отдельное подмножество;
- CSV выгружает те же cycle/deadline данные;
- legacy-назначения без срока остаются `not_applicable`.

Критерии завершения:

- backend policy/unit и frontend tests — PASS;
- Python quality baseline и frontend typecheck — PASS;
- API integration на approved Supabase DEV — PASS: 22 tests под `lms_app`,
  включая реальную RLS-изоляцию; 0 тестовых тенантов после отката;
- production runtime — NOT AUTHORIZED / NOT VERIFIED.

## Этап 2. Надежные напоминания и эскалации — R2a BACKEND + UI, LIVE GATES OPEN

Результат:

- versioned reminder policy у recurring rule;
- tenant-scoped reminder delivery ledger;
- уникальный ключ `participant/occurrence + policy step + channel`;
- bounded claim, retry и stale-claim recovery;
- статусы queued/sent/failed/skipped без содержимого документов и секретов;
- первый уровень — сотруднику, второй — назначенному ответственному;
- ручное повторение использует тот же idempotency key.

Приняты mini-spec и implementation addendum; реализована миграция `0152`:
`docs/product/manager-attention/modules/recurring-reminder-delivery_V1.md`.
Первая поставка R2a — одно опциональное напоминание сотруднику до срока;
повторные шаги и эскалация ответственному остаются R2b, не считаются сделанными.
Реализован отдельный outbox: запись первичного уведомления не переиспользуется.
По умолчанию отправка выключена; исторические назначения не получают рассылку.
Существующий outbox и его delivery semantics не меняются; его recovery entrypoint
получил отдельный bounded batch с проверкой глобального флага. По дополнительному
контракту R2a backend имеет rule PATCH и безопасные статусы; UI-настройки
добавлены в существующие карточки правил. R2b (эскалации) и ручной resend
command остаются открытыми.
Полная приемка требует применения миграции к полному приложению, worker/timer
acceptance и согласованного provider/recipient readback.

Критерии приемки:

- повторный scheduler tick не создает второе сообщение;
- completed/cancelled/skipped occurrence не получает новое напоминание;
- tenant A не читает и не claim-ит ledger tenant B;
- отсутствие email/provider имеет видимый terminal/deferred status;
- руководитель видит факт и результат доставки без доступа к secret/provider
  payload.

## Этап 3. Action center руководителя — PLANNED

Результат:

- группы внимания: `not_started`, `stalled`, `overdue`, `failed_required_quiz`;
- действие: reminder, reassignment, supplemental material, manual review;
- владелец, срок и комментарий действия;
- append-only история состояния;
- сравнение результата до и после действия.

Первая версия не принимает решения за руководителя и не меняет completion или
evidence. Она оркестрирует существующие назначения и уведомления через их
канонические интерфейсы.

Критерии приемки:

- одна проблема не создает два активных одинаковых действия;
- закрытие требует наблюдаемого результата или явного ручного решения;
- отмена не удаляет историю;
- действия и комментарии изолированы tenant/RLS;
- ссылка из action center приводит к точному enrollment/cycle.

## Этап 4. Аналитика слабых вопросов и тем — PLANNED

Результат:

- попытки агрегируются по immutable question snapshot и enrollment instance;
- показываются частота ошибки, число участников и изменение после повторного
  обучения;
- доступны разрезы курса, отдела и должности;
- ответ сотрудника не показывается другим сотрудникам;
- агрегат скрывается ниже утвержденного privacy threshold.

До реализации определить правила для multiple choice, свободного ответа,
изменения редакции вопроса и неполной попытки. Нельзя объединять вопросы только
по тексту или заголовку темы.

## Этап 5. Отдельный onboarding-срез — PLANNED

Результат:

- сохраненный срез новых сотрудников по выбранной программе и периоду;
- этапы not started/in progress/blocked/completed;
- ближайший срок и причина внимания;
- time-to-completion как наблюдаемая метрика;
- переход к действию этапа 3.

Первая версия использует существующие learning paths и training-log read model,
не создает отдельную модель назначения.

## Этап 6. Фактическая матрица компетенций — DEFERRED

Начинать после проверки этапов 3–5 на пилоте. До этого completion и quiz score
не называются фактической компетентностью.

Будущий контур должен отдельно хранить:

- требуемый уровень должности;
- фактическую оценку сотрудника;
- метод и автора оценки;
- подтверждающие материалы;
- срок действия и историю;
- gap и принятое действие.

## Порядок релизов

| Release | Состав | Данные/миграция | Главная приемка |
|---|---|---|---|
| R1 | deadline read model | нет | training log + CSV + overdue filter |
| R2 | reminder policy/ledger | additive | PostgreSQL/RLS + worker/timer + provider readback |
| R3 | action center | additive | полный цикл issue/action/result |
| R4 | weak-topic analytics | возможно additive | privacy + immutable question identity |
| R5 | onboarding view | нет или read-model only | руководитель проходит сценарий без внешней таблицы |
| R6 | competency assessment | отдельный contract | evidence/history/gap lifecycle |

## Пилот и измерение

Пилот: один tenant, одна программа или обязательный курс, одна группа, один
владелец со стороны клиента, заранее согласованный срок.

Измеряем:

- долю завершивших до срока;
- долю не прошедших с первой попытки;
- улучшение после действия;
- время от появления проблемы до действия;
- количество внешних таблиц и ручных сверок;
- число ошибочных или дублирующих уведомлений.

## Текущий следующий шаг

Приемка R1 завершена через штатный `DATABASE_URL` (`lms_app`) на Supabase DEV.
`MIGRATION_DATABASE_URL` применяется только для read-only preflight/проверки
отката, не вместо runtime-role evidence. `SET ROLE` из миграционной учетной записи
на данном DEV недоступен; выдача новых прав не нужна.

Повторяемый запуск из `apps/api`:
`poetry run python ../../scripts/ops/training_log_dev_check.py --execute-tests`.
Только RLS: тот же скрипт с `--runtime-rls`. Скрипт проверяет DEV identity,
блокирует совпадение с существующими test slugs, использует rollback/savepoints
и независимо проверяет отсутствие тестовых тенантов после выполнения. Skipped
обязательный gate не становится PASS.

Следующий этап — полная legacy application/CI migration acceptance для R2a,
release/runtime UI и worker/timer readback, затем отдельно разрешённый live pilot.
Не совмещать миграцию, worker rollout и provider delivery в один непроверяемый
релиз. R3–R5 и R2b этим backend increment не закрыты.

### R2a UI и assembled-chain follow-up, 2026-09-05

Результат: UI настроек и истории на существующих карточках recurring rules;
PATCH только reminder fields, integer 1–30, явные saved/draft/pending/error,
блокировка редактирования при сохранении, lazy history без polling. Устаревшие
ответы после смены auth-контекста/ухода со страницы игнорируются; unknown
status/error показываются понятным текстом, не сырым provider category.
Настройка не объявляет включённой глобальную доставку. R2b не реализован.

Приняты неизменяемые UI-acceptance и login-schema addenda в module directory.
Root при усилении DEV gate обнаружил SQLSTATE `42703`: `has_login_access` был
ошибочно принят за физический users column. Исправлена только ещё не выпущенная
0152, fixtures и регрессия. Прежние 19 minimal-fixture PASS не доказывали
совместимость с реальной структурой — это ограничение теперь закрывает
schema-only clone gate. Остальные ограничения полной схемы остаются ниже.

Итоговые проверки этого прохода:

- Backend: **1063 passed**, 5 warnings; полный unit + четыре соседних no-DB suites.
- Frontend: **37 passed**, 3 suites (`recurringReminders`, `courseAssignmentsFlow`,
  `learningPaths`); `tsc --noEmit` PASS.
- Python quality baseline PASS: ruff=1091, mypy=2356; baseline не менялся.
  Scoped Ruff для новых/изменённых проверочных scripts и schema test PASS.
- Supabase DEV SQL gate: **19 scenarios PASS**, actual lms_app без BYPASSRLS,
  исправленная actual 0152; cleanup **remaining_schemas=0**.
- `--execute --application`: **8 checks PASS** на копии только структуры десяти
  dependency tables DEV head0151 + actual0152. Настоящие HTTP router/role checks,
  ORM/materializer/store/Celery wrapper/email renderer; terminal status и
  повторная задача, timeout/retry с тем же payload/key, rollback всех трёх
  записей, выключение через PATCH до отправки, SQL-helper/Python login parity.
  Cleanup **remaining_schemas=0**, **shared_public_writes=0**, **provider_calls=0**.
- Failure-path test без DB подтверждает sanitized BLOCKED, nonzero exit и
  отсутствие сырого exception payload в отчёте.
- Graphify AST update: **15097 nodes / 35784 edges**, dangling endpoints=0;
  `git diff --check` PASS. `check_application` найден, связи с domain models и
  EmailService сверены с исходниками. Связь `config()` с deploy-test — AMBIGUOUS
  name collision: реальный import `from app.core import config`, не новая
  зависимость от deploy-test. Arrow-function `saveReminderSettings` отдельно
  не индексируется (GRAPH GAP); его caller/PATCH проверены source + RTL.
  15 zero-node input warnings и отсутствие большой HTML-визуализации не
  выдаются за полную семантическую индексацию. Новых product dependencies нет.

Тестовые замены: auth decoding -> synthetic active user (реальный role checker
сохранён), legacy dependency tables -> schema-only LIKE copy + bounded test RLS,
ORM schema map + allowlisted reminder SQL namespace adapter, initial-assignment
notification enqueue stub, broker -> Celery memory transport, Resend -> recorder.
Проверка не доказывает полный historical migration chain, legacy FK/trigger/RLS
parity, настоящий recovery-role process/Valkey/timer, browser визуальный flow,
доставку в почтовый ящик либо production revision. 0152 не применена к shared
DEV/public или production. Commit/push/deploy, реальные письма и activation отсутствуют.

Делегирование: Terra/medium — UI bounded writer, Luna/medium — read-only review;
оба завершены и закрыты. First-pass UI не принят: root запросил pending/auth
guards и семантику отображения; Luna выявил stale error toast, Terra исправил.
Root дополнительно закрыл unmount/смену поколения запросов и сохранил обе
успешную/ошибочную регрессии с реальным async flush. Сообщение Luna о missing
traceback относилось к устаревшему снимку: live import и failure-path test
проверены root. Финальное замечание о toast также пересечено с writer update;
root непосредственно проверил исправленный catch и повторил tests/typecheck.
Actual model IDs/token counters/root elapsed-time accounting — UNKNOWN;
запрошенные модели/effort указаны, денежная стоимость по подписке не выдумана.

### Предыдущая backend-проверка R2a, 2026-09-05

- `pytest tests/unit` вместе с четырьмя соседними no-DB suites: **1061 passed**.
- `learning_reminder_dev_check.py --execute`: **19 SQL contract scenarios PASS**
  в отдельной Supabase DEV схеме с minimal dependency fixtures; реальные
  `lms_app`, migration SQL и Alembic upgrade/downgrade, включая отрицательные
  проверки контекста/ACL, гонку claim, retry horizon, отмену программы,
  расхождение срока, активную доставку при purge и непустую историю при downgrade.
- Cleanup: **remaining_schemas=0**, **shared_public_writes=0**, **provider_calls=0**.
- Реальный login runtime — `lms_app`, без superuser/BYPASSRLS. Recovery-role grant
  проверен через PostgreSQL privileges; реальный recovery connection/процесс
  этим изолированным gate не запускался.
- Python quality baseline PASS: ruff=1091, mypy=2356; baseline не изменялся.
- Финальный Graphify AST index: 15069 nodes / 35748 edges; dangling endpoints = 0.
  Query `PostgresLearningReminderStore` сопоставлен с исходниками store/worker.
  Это навигационное подтверждение, не замена runtime gates. `git diff --check`: PASS.
- Повторное независимое review Luna: нет подтверждённых blockers; замечания о
  точной причине downgrade refusal и изменении срока также исправлены/проверены.

Ограничение доказательства: minimal dependency fixtures — не полный DB clone.
Не выполнялись полный API/worker сценарий на мигрированной схеме приложения,
общая DEV/public миграция, Git push, production deploy, реальная email-доставка.
`LEARNING_REMINDERS_ENABLED` нигде не включался, провайдер не переключался.

Пакеты дешёвым агентам: Terra/medium — store/worker и seam tests; Luna/medium —
renderer и затем независимый SQL review. Первичная приемка worker/renderer
не прошла: root выявил нефинализированный skipped claim и инертный delivery flag;
после одного адресного исправления тесты прошли. SQL и DEV gate оставались у root.
Token counters, независимые model IDs и точное время root review — UNKNOWN.
Профилактика закреплена как проверяемая запись `ERRORS.md`, `REMINDER-001`.

## Пилот делегирования, 2026-09-05

Итоговая проверка текущего R1 diff:

- полный backend unit: **987 passed**;
- полный reporting integration через `DATABASE_URL` / `lms_app`: **22 passed**,
  150.10 s, Supabase DEV head `0151`; superuser/BYPASSRLS = false;
- отдельный runtime-role RLS тест до полного прогона: **1 passed**;
- независимый read-only cleanup по synthetic tenant slugs: **0 осталось**;
- frontend focused RTL/query/locales: **21 passed**, typecheck PASS;
- Python quality baseline: **ruff=1091, mypy=2354**, без регрессии;
- `git diff --check`: PASS; независимый source review Luna: без blockers;
- Graphify AST index: 14949 nodes / 35439 edges; query `deadline_status_sql`
  подтвержден по исходникам, dangling endpoints = 0. Это навигация, не runtime
  evidence и не доказательство направленности всех связей.

Предварительные неуспешные проверки не скрыты: 17 passed / 1 failed (устаревшее
ожидание summary); 19 passed / 3 failed и 20 passed / 2 failed (новые fixtures и
неподходящий `SET ROLE` путь); отдельный RLS запуск сначала выявил зависимость
регистрации ORM-моделей от запуска всего приложения. Исправлены fixtures и runner,
не схема БД/права. Финальный набор прошел без skips. Production, commit/push и
доставка напоминаний в этом проходе не выполнялись.

| Пакет | Запрошенная модель / effort | Приемка с первого раза | Исправления / результат |
|---|---|---|---|
| R1 independent review + R2 source inventory | Luna / medium | review принят | выявлены реальные edge cases; root исправил; повторное review без blockers |
| R1 UI + RTL | Terra / medium | да | 21 focused test, typecheck; root повторил и подтвердил |
| R1 integration fixtures | Terra / medium | нет | root исправил валидность curriculum/sequence, случайную сортировку, слабый completion fixture и isolated imports; затем DEV gate |
| Root integration/acceptance | Astra, текущая задача | не применимо | policy, SQL, tenant predicates, DEV runner, реальная БД и документы |

Независимые runtime model IDs, точные token counters, elapsed и root review time
инструментом не предоставлены/не замерены: UNKNOWN, не ноль. API-цены не
пересчитываются в стоимость подписки. Вывод пилота: collect-only подтверждает
сборку теста, но не валидность DB fixtures; следующий пакет тестов должен явно
ссылаться на существующий lifecycle создания программы и запускаться изолированно
на одном тесте до полного набора. Общие инструкции этим наблюдением не переписаны.
