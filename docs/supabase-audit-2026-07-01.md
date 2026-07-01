# Supabase audit 2026-07-01

## Scope

Проверка выполнена напрямую по секретам из локального `.env`. Значения секретов в отчет не включены.

Проверялись:

- доступ к Supabase Postgres через `DATABASE_URL`;
- доступ к Supabase Storage через `SUPABASE_URL` и `SUPABASE_KEY`;
- состояние Alembic-миграций;
- целостность `enrollments` после разделения tenant-admin и methodologist/teacher функций;
- RLS/FORCE RLS для tenant-scoped таблиц.

## Findings

1. База была на `alembic_version = 0036`, при этом репозиторий уже содержал более новые миграции.
2. Миграция `0037_backfill_positions_created_at.py` не содержала Alembic metadata (`revision`, `down_revision`, `branch_labels`, `depends_on`), из-за чего граф миграций был неполным.
3. В production-данных были некорректные назначения курсов:
   - 2 manual enrollments на пользователя с ролью `admin`;
   - 1 orphan position enrollment.
4. В Storage найден ожидаемый bucket `Kamilya LMS`.
5. У части tenant-scoped таблиц RLS/FORCE RLS был не включен или не зафиксирован через актуальные миграции.
6. Текущий `DATABASE_URL` подключается к базе как `postgres`; у этой роли включен `BYPASSRLS`. Это означает, что RLS уже настроен на уровне схемы, но runtime-подключение через эту роль может обходить политики.

## Applied Changes

1. Исправлена metadata миграции `0037_backfill_positions_created_at.py`.
2. Supabase Postgres обновлен Alembic-командой до `0040 (head)`.
3. Добавлена и применена миграция `0039_rls_new_tenant_tables.py`:
   - включает RLS;
   - включает FORCE RLS;
   - пересоздает policy `tenant_isolation`;
   - выдает `lms_app` CRUD grants для tenant-scoped таблиц, добавленных после ранних миграций.
4. Добавлена и применена миграция `0040_rls_user_invitations.py` для `user_invitations`.
5. `provider_keys` намеренно исключена из `0039`, потому что `tenant_id IS NULL` используется как глобальный platform provider key в v1.
6. Удалены 3 некорректные строки из `enrollments`.

## Post-Check

После применения изменений:

- `alembic_version = 0040`;
- проверено 28 tenant-scoped таблиц, все с `rls_enabled = true` и `force_rls = true`;
- `enrollments_total = 7`;
- `missing_user = 0`;
- `for_non_students = 0`;
- bucket `Kamilya LMS` найден.

Распределение пользователей по ролям на момент проверки:

- `admin`: 3;
- `student`: 16;
- `superadmin`: 2;
- `teacher`: 1.

## Runtime Cutover 2026-07-01

После аудита был выполнен runtime cutover:

- для роли `lms_app` задан новый пароль;
- локальный `.env` обновлен: `DATABASE_URL` теперь подключается через `lms_app`;
- локальный `.env` обновлен: `MIGRATION_DATABASE_URL` подключается через admin-role для Alembic DDL-миграций;
- подключение проверено напрямую: `current_user = lms_app`, `rolbypassrls = false`;
- Render service `kamilya-lms-api` обновлен через Render API;
- Render deploy `dep-d92asddckfvc73dfp46g` дошел до `live`;
- production health-check `https://kamilya-lms-api.onrender.com/api/v1/health` вернул `{"status":"ok","app":"Kamilya LMS"}`.
- Render env `MIGRATION_DATABASE_URL` добавлен через Render API; deploy `dep-d92b0kbtqb8s73f6ndkg` дошел до `live`.
- VPS `kamilya-worker` env обновлен после установки SSH-ключа: `DATABASE_URL` использует `lms_app`, `MIGRATION_DATABASE_URL` использует admin-role; `kamilya-worker.service` перезапущен и активен.

Новый пароль хранится только в локальном `.env` и Render env, значения в git не добавлялись.

## Remaining Operational Risk

Render runtime database connection переключен на роль без `BYPASSRLS` (`lms_app`).

Текущее состояние ролей после переключения:

- `lms_app`: `rolbypassrls = false`, `rolcanlogin = true`;
- `postgres`: `rolbypassrls = true`, `rolcanlogin = true`;
- `service_role`: `rolbypassrls = true`, `rolcanlogin = false`.

`MIGRATION_DATABASE_URL` заведен отдельно от runtime `DATABASE_URL`: Alembic использует admin connection, а приложение и worker в runtime используют `lms_app`.
