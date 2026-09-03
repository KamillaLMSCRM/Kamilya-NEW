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
- [Пакет локальных документов для первого ломбарда](customer/pawnshop/README.md)
- [Авторизация tenant: email, Telegram и Resend](architecture/2026-07-10_tenant-auth-email-telegram-resend.md)
- [Регистрация tenant и trial](product/tenant-registration-trial-flow.md)

## Продажи и демонстрации

- [Сценарий живой демонстрации](presentations/2026-07-28_live-product-demo-runbook-ru.md)
- [Интерактивные презентации](presentations/README.md)

## Разработчикам

- [Описание продукта](../PROJECT.md)
- [Журнал ошибок и предотвращения повторов](../ERRORS.md)
- [Live OpenAPI](https://kamilya-lms-api.onrender.com/docs)
- [Архитектурные решения](adr/)
- [ADR-0024: контрактно-модульная разработка](adr/0024-contract-first-modular-delivery.md)
- [ADR-0025: роли, change control и исполняемые contract tests](adr/0025-contract-governance-and-verification.md)
- [Стандарт контрактных модулей](product/contract-modules/README.md)
- [EPIC-APPROVAL-FOLLOWUP-01: уведомления и напоминания согласования](product/contract-modules/EPIC-APPROVAL-FOLLOWUP-01/EPIC_V1.md)
- [Общая инструкция для агентов V2](product/contract-modules/AGENT_INSTRUCTION_V2.md)
- [Шаблон цели и сквозной цепочки V2](product/contract-modules/templates/EPIC_CHAIN_SPEC_V2.md)
- [Шаблон mini-spec модуля V2](product/contract-modules/templates/MODULE_MINI_SPEC_V2.md)
- [Архив V1: общая инструкция](product/contract-modules/AGENT_INSTRUCTION_V1.md)
- [Архив V1: шаблон цели](product/contract-modules/templates/EPIC_CHAIN_SPEC_V1.md)
- [Архив V1: шаблон mini-spec](product/contract-modules/templates/MODULE_MINI_SPEC_V1.md)
- [ADR-0015: события обучения и подтверждение результата](adr/0015-training-evidence-and-step-up-confirmation.md)
- [ADR-0017: версионированные отраслевые заготовки курсов](adr/0017-versioned-industry-course-blueprints.md)
- [Celery worker](INFRA_CELERY_WORKER.md)
- [VPS и сервисы](VPS_CONNECTION_GUIDE.md)
- [Backup и restore](BACKUP_RESTORE_RUNBOOK.md)

## Правила актуальности

1. Текущее состояние production фиксируется только в
   `PROJECT-CONTEXT.md` и `PRODUCTION_READINESS.md`.
2. Открытые продуктовые задачи фиксируются только в `PRODUCT_BACKLOG.md`.
3. Выполненный эпик обновляет продуктовую или эксплуатационную документацию;
   отдельный датированный «финальный отчёт» не создаётся.
4. Принятые versioned EPIC, module mini-spec, contract и impact-addendum
   документы сохраняются рядом с новой версией; старый файл не переписывается и
   явно помечается как superseded. Временные execution plans и отчёты после
   переноса устойчивого результата по-прежнему удаляются и остаются в Git.
5. Секреты, пароли, токены и значения `.env` в документацию не добавляются.
