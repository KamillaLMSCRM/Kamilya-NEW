# Документация Kamilya LMS

Этот индекс содержит только действующие документы. История решений и
выполненных работ доступна в Git, но не используется как описание текущего
production.

## Начать отсюда

- [Контекст проекта и production](PROJECT-CONTEXT.md)
- [Готовность первого production-тенанта](PRODUCTION_READINESS.md)
- [Актуальный продуктовый backlog](PRODUCT_BACKLOG.md)
- [Внутренняя документация](PROJECT_INTERNAL_DOCUMENTATION.md)
- [Handoff для нового Codex или другого компьютера](CODEX_HANDOFF.md)

## Пользователям

- [Руководство пользователя](USER_DOCUMENTATION_RU.md)
- [Руководство методолога: выпуск и назначение курса](methodologist-course-release-guide-ru.md)
- [Авторизация tenant: email, Telegram и Resend](architecture/2026-07-10_tenant-auth-email-telegram-resend.md)
- [Регистрация tenant и trial](product/tenant-registration-trial-flow.md)

## Разработчикам

- [Описание продукта](../PROJECT.md)
- [Live OpenAPI](https://kamilya-lms-api.onrender.com/docs)
- [Архитектурные решения](adr/)
- [Celery worker](INFRA_CELERY_WORKER.md)
- [VPS и сервисы](VPS_CONNECTION_GUIDE.md)
- [Уроки проекта](LESSONS.md)

## Правила актуальности

1. Текущее состояние production фиксируется только в
   `PROJECT-CONTEXT.md` и `PRODUCTION_READINESS.md`.
2. Открытые продуктовые задачи фиксируются только в `PRODUCT_BACKLOG.md`.
3. Выполненный эпик обновляет продуктовую или эксплуатационную документацию;
   отдельный датированный «финальный отчёт» не создаётся.
4. Исторические ТЗ и отчёты удаляются из рабочего дерева. При необходимости
   они доступны через Git history.
5. Секреты, пароли, токены и значения `.env` в документацию не добавляются.
