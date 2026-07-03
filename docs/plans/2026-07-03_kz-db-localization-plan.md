# План локализации БД и данных Kamilya LMS в РК

Дата: 2026-07-03

## Цель

Подготовить Kamilya LMS к запуску первых B2B-тенантов с хранением персональных данных граждан РК в инфраструктуре на территории Казахстана.

## Исходная позиция

- Hosted Supabase сейчас используется как основной PostgreSQL/SaaS-контур.
- Для РК hosted Supabase слаб как целевой контур хранения ПДн, потому что публичного региона Kazakhstan у Supabase нет.
- Практически лучший маршрут для продукта: managed PostgreSQL в РК + backend Kamilya как единственный рабочий API-контур.
- Self-hosted Supabase в РК рассматривать только если инвентаризация покажет критическую зависимость от Supabase Auth/Storage/Realtime/PostgREST.

## Решение по направлению

Основной вариант: managed PostgreSQL в Казахстане.

Shortlist провайдеров:

1. Yandex Cloud Kazakhstan Managed PostgreSQL.
2. Servercore Kazakhstan PostgreSQL as a Service.
3. VK Cloud Kazakhstan DBaaS.

Fallback: self-hosted PostgreSQL/Supabase на VPS/IaaS в РК, если managed DBaaS не покрывает `pgvector`, бэкапы/PITR, private network или договорные требования.

## Этап 1. Инвентаризация Supabase-зависимостей

Проверить и зафиксировать:

- таблицы, схемы, extensions, indexes;
- RLS policies и места, где приложение реально рассчитывает на RLS;
- Supabase Auth, Storage, Realtime, Edge Functions, cron/webhooks;
- bucket-и с документами и наличие ПДн в файлах;
- где хранятся embedding-и и исходные chunks;
- логи, audit events и фоновые job payloads, где может быть ПДн.

Результат: `docs/audits/<date>_supabase_dependency_inventory.md`.

## Этап 2. Проверка провайдера

Для каждого кандидата запросить:

- физическая локация primary DB;
- где хранятся backups, snapshots, WAL/PITR, object storage, service logs;
- договорная гарантия, что primary и резервные копии остаются в РК;
- версии PostgreSQL и поддержка `pgvector`;
- private network, firewall/security groups, TLS, audit logs;
- PITR, retention, RPO/RTO, restore drill;
- SLA именно для managed database;
- процесс удаления данных после расторжения договора.

Результат: сравнительная таблица и выбранный staging-провайдер.

## Этап 3. Staging-контур в РК

Поднять staging PostgreSQL в РК и выполнить:

- создать отдельный `MIGRATION_DATABASE_URL`;
- прогнать Alembic migrations;
- проверить расширения PostgreSQL, включая `pgvector`, если используется;
- подключить backend staging;
- запустить smoke-flow: регистрация тенанта, email OTP, загрузка документа, генерация курса, назначение курса, прохождение учеником, сертификат;
- проверить tenant isolation на уровне API и DB-запросов.

Результат: staging DB в РК, подтвержденный smoke-test.

## Этап 4. Storage и документы

Перенести объектное хранилище документов в РК:

- исходные документы тенантов;
- сгенерированные материалы;
- сертификаты;
- временные файлы импорта;
- бэкапы storage.

AI-провайдеры должны получать минимальный набор данных. Для документов с ПДн нужен отдельный режим: маскирование, явное согласие/основание или локальная обработка.

## Этап 5. Production cutover

Перед переключением:

- freeze window;
- финальный dump/export из текущей БД;
- restore в РК;
- миграционная сверка counts/checksums по ключевым таблицам;
- переключение `DATABASE_URL`;
- проверка auth/logout/login на `app.kml.kz`;
- проверка первого тенанта end-to-end;
- включить мониторинг, алерты, backup verification.

Rollback:

- не удалять старый контур до окончания проверки;
- держать точку восстановления до cutover;
- иметь documented rollback DNS/env plan.

## Открытые риски

- Нужно юридически подтвердить трактовку хранения ПДн, бэкапов, логов и AI-передачи.
- Одна зона доступности в РК у части провайдеров может ограничить отказоустойчивость.
- Если в Supabase используются специфичные сервисы, простой перенос PostgreSQL будет недостаточен.
- AI/embedding-провайдеры могут получать текст документов; это отдельный data-transfer риск.

## Ближайшие действия

1. Сделать Supabase dependency inventory по текущему проекту.
2. Проверить `pgvector` и required extensions у трех DBaaS-кандидатов.
3. Поднять staging PostgreSQL в РК.
4. Прогнать migrations и первый tenant smoke-flow.
5. После подтверждения staging готовить production cutover.
