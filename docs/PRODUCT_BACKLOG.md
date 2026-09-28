# Kamilya LMS: актуальный продуктовый backlog

**Дата:** 2026-09-28
**Область:** открытые продуктовые и UX-задачи. Выполненные эпики здесь не
хранятся.

Каноническая карта состояния корпоративного продукта и уровней доказательности:
[`product/CORPORATE_READINESS_MAP_2026-09-26.md`](product/CORPORATE_READINESS_MAP_2026-09-26.md).
Этапы 0 и 1 закрыты как baseline документами
[`product/CORPORATE_STAGE1_ACCEPTANCE_2026-09-26.md`](product/CORPORATE_STAGE1_ACCEPTANCE_2026-09-26.md)
и
[`product/CORPORATE_STAGE1_RESULT_2026-09-26.md`](product/CORPORATE_STAGE1_RESULT_2026-09-26.md).
Текущая работа ведётся по
[`plans/2026-09-28_source-actuality-and-retraining.md`](plans/2026-09-28_source-actuality-and-retraining.md).

## P0: замыкание корпоративного контура

Corporate Readiness stage 3 закрыт в production на `v0.11.13`: синтетический
человеческий сценарий подтвердил повторное назначение при сохранении завершённой
истории и видимого основания. Управление актуальностью источника реализовано и
принято локально и в изолированном Supabase DEV: владелец и дата пересмотра,
детерминированный анализ новой версии, видимое влияние на курсы и только явное
решение методиста о новом draft и повторном обучении. Открытый P0 — выпустить
этот точный кандидат через DEV и production с браузерной приёмкой.

Обязательные границы: immutable опубликованные версии и завершённая история не
переписываются; AI не публикует и не переназначает автоматически; tenant/RLS,
идемпотентность решения, mobile UX и cleanup подтверждаются через канонические
local/CI и изолированный Supabase DEV контуры до любого production-релиза.

## P1: Corporate Readiness — открытые части

1. Сохранять reconciliation dashboard, mandatory-training matrix, training
   log, CSV/PDF/ZIP export и evidence package как обязательную регрессию одной
   occurrence/enrollment модели. Несовпадение счётчиков является release
   blocker.

## P1: качество курсов и тестов

1. Считать покрытие source entities/facts и смысловых блоков, а не количество
   созданных уроков или вопросов.
2. Проверять содержательность объяснений после ответа: объяснение раскрывает
   причину, а не повторяет правильный вариант.
3. Выполнять повторяемые PDF/XLSX replay на утверждённом корпусе и показывать
   точные непокрытые блоки без quota padding.
4. Сохранять внутренние sanitized diagnostics до публикации draft; TypeSafe,
   Laya и другие внешние оценщики остаются только development-инструментами и
   не входят в клиентский production-flow.

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
