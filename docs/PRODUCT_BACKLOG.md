# Kamilya LMS: актуальный продуктовый backlog

**Дата:** 2026-09-26
**Область:** открытые продуктовые и UX-задачи. Выполненные эпики здесь не
хранятся.

Каноническая карта состояния корпоративного продукта и уровней доказательности:
[`product/CORPORATE_READINESS_MAP_2026-09-26.md`](product/CORPORATE_READINESS_MAP_2026-09-26.md).
План текущей приёмки:
[`product/CORPORATE_STAGE1_ACCEPTANCE_2026-09-26.md`](product/CORPORATE_STAGE1_ACCEPTANCE_2026-09-26.md).
Фактический результат:
[`product/CORPORATE_STAGE1_RESULT_2026-09-26.md`](product/CORPORATE_STAGE1_RESULT_2026-09-26.md).

## P0: корпоративная приёмка текущего продукта

До следующего крупного продуктового эпика пройти три синтетических архетипа:

1. небольшая компания с простой структурой;
2. компания с филиалами и разной глубиной организационной структуры;
3. регулируемая организация с повторным обучением, подтверждением результата,
   подписанным экземпляром и evidence package.

Обязательные границы: один source of truth для dashboard/training log/export,
tenant isolation, точное основание назначения, сохранение истории после
повторного назначения, идемпотентный import/assignment, mobile UX и cleanup без
клиентских записей. Производительность и DB/RLS проверять только через
канонические local/CI и изолированный Supabase DEV контуры. В production
разрешён только существующий синтетический tenant с точным readback и cleanup.

## P1: Corporate Readiness

1. Единая матрица обязательного обучения: сотрудник, должность, требование,
   основание, срок, состояние, версия курса и следующая дата обучения.
2. Для каждого назначения показывать объяснимое `why assigned`: ручное
   назначение, должность, подразделение, группа, программа, recurring rule или
   изменение версии источника.
3. Довести action center и methodologist dashboard до deployed browser
   acceptance. Агрегаты без точного server-side фильтра не должны выглядеть
   кликабельными действиями.
4. Добавить ограниченную область ответственности за обучение по ветви
   организационной структуры или группе без возврата глобальных ролей
   `teacher`/`org_admin`.
5. Сверять dashboard, training log, CSV/PDF/ZIP export и evidence package по
   одной occurrence/enrollment модели. Несовпадение счётчиков является
   release blocker.
6. Добавить управление актуальностью источника: владелец, утверждающий, дата
   пересмотра, новая версия, связанные курсы и решение о повторном обучении.

## P1: доказательства внутреннего обучения

1. Реализовать отдельный фактический workflow комиссии для внутренней
   аттестации. Tenant procedure уже хранит утверждение, состав/quorum и правило
   решения, но не исполняет заседание и не создаёт regulated evidence.
2. Реализовать отдельный workflow уполномоченного решения о допуске. Успешный
   тест, completion и generic correction не должны выдавать допуск.
3. Добавить scheduled retention purge, отчёт исполнения, retry/alerting и
   backup retention. Tenant policies, legal hold, persistent cursor и bounded
   dry-run/manual purge уже реализованы.
4. Для первого ломбарда: шаблоны программ по финансовым продуктам и ПОД/ФТ
   после проверки локальных актов. Внутренний тест Kamilya не заменяет
   официальный тест АФМ. Базовая RU/KK заготовка курса по информационной
   безопасности уже реализована; её следующие версии требуют назначенного
   редакционного владельца и периодической проверки актуальности.

Уже реализовано: append-only training/knowledge-check
events, correction/revocation/legal hold core, purpose-bound OTP, learner
own-read, индивидуальный и групповой PDF/ZIP, tenant procedures, restricted
evidence share и manual retention purge. OTP не является ЭЦП.

## P1: первый рабочий день tenant

Bulk invitation delivery через Celery, lifecycle/provider id/errors, manual
fallback, worker parity и production smoke реализованы. В backlog остаётся
операционный delivery monitoring.
## P1: эксплуатация

1. Delivery monitoring для email с tenant-safe диагностикой.
2. Безопасная очистка зависших jobs после определения retry/retention policy.
3. Сверить ORM metadata с исторической схемой из 77 Alembic revisions:
   описать SQL-only `document_embeddings`, согласовать типы, индексы,
   внешние ключи и nullable/default. До завершения сверки не применять
   autogenerate output: текущий drift содержит разрушительные remove-операции.
4. Добавить oldest-job age, task failure rate, provider 429/timeout и разрез
   queue depth по tenant без раскрытия tenant PII.
5. Провести отдельный capacity acceptance на реальных многостраничных сканах и
   платный прогон 10 генераций; текущая оценка 50 задач не является SLA.
6. Выпустить и принять durable LMS→CRM lead outbox: migration/API/worker parity,
   минутный recovery timer, общий secret и end-to-end smoke с идемпотентным
   повтором. После подтверждения перенести evidence в `PRODUCTION_READINESS.md`
   и удалить этот пункт.

## P1: безопасный рефакторинг без изменения поведения

1. Продолжить разделение frontend по workflow-интерфейсам: после вынесенного
   polling/cancel/retry контура AI generation отделить review/regeneration, а
   затем применить тот же подход к staff import. Делить по state transitions и
   пользовательским действиям, а не по размеру файлов; тестировать наблюдаемые
   loading/error/cancel/retry/review состояния.

Не менять в рамках этой работы канонический
`positions.assignment_service.recompute_enrollments` и не дробить общий
`web/src/lib/api.ts`: оба уже дают leverage и locality через компактный
interface.

## P2: расширение продукта

1. SCORM 1.2 UX после проверки реальных пакетов; SCORM 2004 не заявлять.
2. Kiosk после device/privacy QA.
3. AI-помощник обучающегося с grounded-ответами и явными источниками.
4. Feedback/notifications вернуть в меню только после определения владельца,
   delivery-модели, статусов и privacy.
5. KZ localization: БД, object storage, backup и договорные формулировки;
   реальный pawnshop acceptance test выполнять только после готовности этого
   контура и локальных процедур клиента.
6. Полная матрица компетенций: оценка фактического уровня сотрудника,
   подтверждающие материалы, история оценки и gap-анализ относительно
   требований должности. До этого компетенции остаются частью карточки
   должности, а не отдельным пунктом меню.
7. Довести recurring learning cycles по
   [ADR-0019](adr/0019-recurring-learning-cycles.md) в следующем порядке:
   1. сначала сделать completion, attempt, progress, certificate и training
      log однозначно enrollment-instance based без изменения текущего
      поведения;
   2. поверх уже реализованных tenant-scoped draft rules добавить immutable
      dated instance, participant и per-user override/audit;
   3. добавить scheduler, idempotent reminder ledger, notification queue,
      stale-claim recovery и operational smoke;
   4. включить course cycles, затем program cycles, и только после этого
      добавить cycle/overdue read model в training log.

## P2: локальность staff import

Отделить CSV/XLSX parsing adapters и их общий parser contract от
tenant-scoped preview/commit. Сохранить `commit_import` как application
interface и существующее переиспользование из `create_manual_staff_member`;
не дублировать hierarchy, email-conflict и apply-rules правила. Общий parser
contract прогонять для обоих форматов, а DB/RLS поведение проверять через
существующие integration tests `commit_import`.

## P2: tenant Telegram-бот для уведомлений

Сохранение, шифрование и проверка токена tenant-бота уже реализованы. До
завершения следующего контура не заявлять его как действующий канал доставки:
текущий webhook и вход по коду используют общий системный бот Kamilya, а
приглашения и объявления доставляются по email.

1. После проверки токена автоматически регистрировать отдельный webhook с
   tenant-scoped secret и безопасной ротацией токена.
2. Формировать одноразовую deep link вида
   `t.me/<tenant_bot>?start=<activation_token>` и связывать Telegram ID только
   после проверки invitation token; username не считать идентификатором.
3. Добавить выбор Telegram как канала приглашения и доставку уведомлений о
   назначении курса, сроке, результате теста, готовом сертификате и объявлениях.
4. Сообщения должны содержать минимально необходимую информацию и кнопку
   перехода в Kamilya; сам курс остаётся в web-интерфейсе.
5. Добавить opt-out, delivery status/retry, rate limit, аудит, удаление связи и
   tenant-isolation tests. Токен бота не возвращать в API и не писать в логи.
6. Acceptance: новый сотрудник связывает Telegram по одноразовой ссылке,
   получает назначение и напоминание, открывает курс, а другой tenant не может
   отправить сообщение через его бота или переиспользовать activation token.

## Не возвращать

- роль `teacher`;
- роль `org_admin`;
- управление курсами и обучающимися в кабинете tenant admin;
- `/admin/enrollments` как самостоятельный продуктовый экран;
- дублирующие редакторы должности, компетенций или course rules;
- незавершённые `Обратная связь` и `Уведомления` в основной sidebar.

## Приоритизация

Задача попадает в разработку только если у неё есть:

1. владелец роли и канонический route;
2. пользовательский результат;
3. API/data source of truth;
4. критерии desktop/mobile QA;
5. тесты и production verification.
