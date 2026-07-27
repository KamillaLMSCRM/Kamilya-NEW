# Kamilya LMS: backup и restore runbook

**Обновлено:** 2026-07-27  
**Контур:** production PostgreSQL в Supabase, backup job на worker VPS.

## Компоненты

- backup script: `/opt/kamilya-worker/scripts/backup.sh`;
- restore script: `/opt/kamilya-worker/scripts/restore.sh`;
- encrypted archives: `/opt/kamilya-backups/kamilya_*.dump.enc`;
- backup logs: `/var/log/kamilya-backup`;
- timer: `kamilya-backup.timer`;
- root-only config: `/etc/kamilya/backup.env`;
- root-only libpq password: `/etc/kamilya/backup.pgpass`;
- root-only encryption passphrase: `/etc/kamilya/backup.pass`.

Не печатать содержимое файлов из `/etc/kamilya`.

## Проверка backup

```bash
systemctl is-active kamilya-backup.timer
systemctl list-timers kamilya-backup.timer --all
systemctl start kamilya-backup.service
systemctl show kamilya-backup.service -p Result -p ExecMainStatus
find /opt/kamilya-backups -maxdepth 1 -type f \
  -name 'kamilya_*.dump.enc' -printf '%f %s bytes mode=%m\n'
```

Успешный backup:

- имеет суффикс `.dump.enc`;
- имеет режим `0600`;
- проходит decrypt + `pg_restore --list` внутри backup script;
- не оставляет `.dump`, `.part` или `.dump.part`;
- не удаляет последний валидный архив при retention.

## Restore в существующий Supabase-compatible cluster

Перед запуском создать отдельную пустую target DB и отдельный `PGPASSFILE`.
Production target заблокирован без трёх явных подтверждений.

```bash
export DB_HOST='<target-host>'
export DB_PORT='5432'
export DB_USER='<migration-user>'
export PGPASSFILE='<root-only-pgpass>'
export PGSSLMODE='require'
export PRODUCTION_DB_NAME='<actual-production-db>'
export BACKUP_PASSPHRASE_FILE='<root-only-passphrase-file>'
export LOG_DIR='<restore-log-directory>'

/opt/kamilya-worker/scripts/restore.sh \
  --backup-file '<archive.dump.enc>' \
  --target-db '<empty-target-db>' \
  --yes
```

## Portable restore вне Supabase

Обычный PostgreSQL/pgvector не содержит Supabase Vault. Использовать явный
profile:

```bash
/opt/kamilya-worker/scripts/restore.sh \
  --backup-file '<archive.dump.enc>' \
  --target-db '<empty-target-db>' \
  --portable-supabase \
  --yes
```

Profile:

- исключает extension `supabase_vault`;
- исключает platform-owned table data schema `vault`;
- создаёт отсутствующую роль `lms_app` как `NOLOGIN`, чтобы восстановить
  RLS policies.

После restore оператор отдельно задаёт `LOGIN` и новый runtime password для
`lms_app`, обновляет `DATABASE_URL`, проверяет RLS/tenant context и только затем
подключает API/worker. Restore script намеренно не создаёт runtime password.

## Обязательная проверка restore

1. Alembic revision совпадает с repository head.
2. Количество public tables больше нуля.
3. Проверены агрегаты tenants, courses, enrollments и certificates.
4. `lms_app` существует; до provisioning он `NOLOGIN`.
5. Plaintext dump отсутствует после завершения.
6. Выполнены API migration check, tenant isolation gate и business smoke.
7. Одноразовая target DB и локальные копии удалены после фиксации результата.

## Последний подтверждённый drill

2026-07-27 production archive восстановлен в одноразовый PostgreSQL 17 +
pgvector:

- Alembic `0078`;
- 56 public tables;
- данные LMS восстановлены;
- plaintext residue отсутствует;
- одноразовый контейнер и локальная копия удалены.

Агрегаты относятся к тестовым данным production-контура и не являются
бизнес-метриками.
