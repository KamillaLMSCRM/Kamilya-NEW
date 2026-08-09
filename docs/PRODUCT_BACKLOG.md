# Kamilya LMS: актуальный продуктовый backlog

**Дата:** 2026-08-08
**Область:** открытые продуктовые и UX-задачи. Выполненные эпики здесь не
хранятся.

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

1. Добавить host CPU/RAM/disk и состояние трёх Celery worker к агрегированной
   operational console. Пятиминутный watchdog и queue-depth alert уже работают.
2. Delivery monitoring для email с tenant-safe диагностикой.
3. Безопасная очистка зависших jobs после определения retry/retention policy.
4. Сверить ORM metadata с исторической схемой из 77 Alembic revisions:
   описать SQL-only `document_embeddings`, согласовать типы, индексы,
   внешние ключи и nullable/default. До завершения сверки не применять
   autogenerate output: текущий drift содержит разрушительные remove-операции.
5. Добавить oldest-job age, task failure rate, provider 429/timeout и разрез
   queue depth по tenant без раскрытия tenant PII.
7. Провести отдельный capacity acceptance на реальных многостраничных сканах и
   платный прогон 10 генераций; текущая оценка 50 задач не является SLA.
8. Выпустить и принять durable LMS→CRM lead outbox: migration/API/worker parity,
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
5. Группировка навигации `Квалификации` и `Контроль и результаты` после
   устранения дублирующих route ownership.
6. KZ localization: БД, object storage, backup и договорные формулировки;
   реальный pawnshop acceptance test выполнять только после готовности этого
   контура и локальных процедур клиента.
7. Полная матрица компетенций: оценка фактического уровня сотрудника,
   подтверждающие материалы, история оценки и gap-анализ относительно
   требований должности. До этого компетенции остаются частью карточки
   должности, а не отдельным пунктом меню.
8. Самостоятельные assessment-кампании создавать отдельной сущностью только
   после определения аудитории, попыток, сроков и отчётности. Тесты уроков
   отдельно от курса не назначать.

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
