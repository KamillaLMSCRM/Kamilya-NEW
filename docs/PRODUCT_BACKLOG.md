# Kamilya LMS: актуальный продуктовый backlog

**Дата:** 2026-08-07
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
4. Для первого ломбарда: шаблоны программ по финансовым продуктам,
   информационной безопасности и ПОД/ФТ после проверки локальных актов.
   Внутренний тест Kamilya не заменяет официальный тест АФМ.

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

## P1: безопасный рефакторинг без изменения поведения

1. Углубить `ai.job_service` до единого интерфейса отправки AI-задачи:
   admission, quota/budget reservation, commit, Celery dispatch и compensation
   при недоступной очереди. Перевести на него генерацию курса, регенерацию
   модуля и урока; в router оставить transport/RBAC. Проверять через fake
   dispatcher и тестовую PostgreSQL-транзакцию, не вынося гипотетический
   repository interface; endpoint tests сократить до transport/RBAC contracts.
2. Перевести `/quizzes` с прямых `fetch` и ручного bearer/error handling на
   существующий `web/src/lib/api.ts`, сохранив endpoints и payloads. Не
   добавлять отдельный feature adapter, пока он не скрывает реальный
   quiz-authoring workflow: pass-through wrapper является неглубоким модулем.
3. Разделить AI generation и staff frontend не по размеру файлов, а по
   workflow-интерфейсам: state transitions + действия за небольшим hook/reducer
   interface, presentation panels без orchestration. Тестировать наблюдаемые
   состояния loading/error/cancel/retry/review, а не внутренние `useState` и
   формат HTTP-запросов.

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
