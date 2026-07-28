# Kamilya LMS: актуальный продуктовый backlog

**Дата:** 2026-07-28
**Область:** открытые продуктовые и UX-задачи. Выполненные эпики здесь не
хранятся.

## P1: первый рабочий день tenant

1. Автоматическая отправка invitation link через Resend, история, повторная
   отправка и причина недоставки. Сейчас ссылка передаётся вручную.
2. Провести controlled rollout и read-only production smoke AI-рекомендаций
   аудитории курса на тестовом tenant. Реализация уже находится в `master`;
   помощник не создаёт назначения, финальное действие остаётся на
   `/assignments`. План и критерии smoke:
   [2026-07-28_methodologist-ai-audience-advisor.md](plans/2026-07-28_methodologist-ai-audience-advisor.md).

## P1: эксплуатация

1. Добавить host CPU/RAM/disk и Celery worker health к текущей агрегированной
   operational console.
2. Delivery monitoring для email с tenant-safe диагностикой.
3. Безопасная очистка зависших jobs после определения retry/retention policy.

## P2: расширение продукта

1. SCORM 1.2 UX после проверки реальных пакетов; SCORM 2004 не заявлять.
2. Kiosk после device/privacy QA.
3. AI-помощник обучающегося с grounded-ответами и явными источниками.
4. Feedback/notifications вернуть в меню только после определения владельца,
   delivery-модели, статусов и privacy.
5. Группировка навигации `Квалификации` и `Контроль и результаты` после
   устранения дублирующих route ownership.
6. KZ localization: БД, object storage, backup и договорные формулировки.

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
