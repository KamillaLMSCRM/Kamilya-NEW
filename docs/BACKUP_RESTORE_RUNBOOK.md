# Kamilya LMS: backup и restore runbook

**Обновлено:** 2026-08-20
**Контур:** KZ production PostgreSQL 17 + pgvector на CT125. Render/Supabase —
development/demo/rollback и не являются источником production backup.

## Компоненты

- database backup timer: `kamilya-pg-backup.timer` на CT125;
- blob backup timer: `kamilya-blob-backup.timer` на VM126;
- database archives: encrypted `*.dump.gpg` + SHA-256 sidecar, mode `0600`;
- точные ExecStart, каталоги и root-only environment всегда брать из
  `systemctl cat kamilya-pg-backup.service` на текущем CT125, а не из старых
  Supabase/VPS заметок;
- recovery credentials, encryption key и runtime URL остаются только в
  root-only конфигурации узлов.

Не печатать содержимое файлов из `/etc/kamilya`.

## Проверка backup

```bash
systemctl is-active kamilya-pg-backup.timer
systemctl list-timers kamilya-pg-backup.timer --all
systemctl cat kamilya-pg-backup.service
systemctl start kamilya-pg-backup.service
systemctl show kamilya-pg-backup.service -p Result -p ExecMainStatus
```

Успешный backup:

- имеет суффикс `.dump.gpg` и SHA-256 sidecar;
- имеет режим `0600`;
- использует authenticated GPG encryption, а не unauthenticated OpenSSL CBC;
- до публикации проходит checksum + decrypt + `pg_restore --list` внутри
  `scripts/backup.sh`;
- при включённом MinIO требует governance retention, повторно скачивает архив
  и сравнивает его побайтно с локальной копией;
- не оставляет `.dump`, `.part` или `.dump.part`;
- не удаляет последний валидный архив при retention.

Репозиторный `scripts/backup.sh` не считается развёрнутым только потому, что
локальные contract tests зелёные. Перед заменой production unit оператор должен
сверить `ExecStart`, выполнить dry-run, создать новый backup и проверить offsite
round-trip/retention на утверждённом KZ target.

## Restore в одноразовый KZ PostgreSQL 17 + pgvector

Перед запуском создать отдельную пустую target DB и отдельный `PGPASSFILE`.
Версионированная команда — `scripts/kz-restore-drill.sh`. Она не содержит
production override: совпадение target с `PRODUCTION_DB_NAME` всегда является
ошибкой. Непустая target DB также всегда отклоняется.

Обязательный первый запуск без записи:

```bash
EXPECTED_ALEMBIC_HEAD=0120 \
  scripts/kz-restore-drill.sh \
  --backup-file /approved/path/kamilya_YYYYMMDDTHHMMSSZ.dump.gpg \
  --target-db kamilya_restore_drill \
  --dry-run
```

После успешного dry-run и отдельного подтверждения disposable target:

```bash
EXPECTED_ALEMBIC_HEAD=0120 \
  scripts/kz-restore-drill.sh \
  --backup-file /approved/path/kamilya_YYYYMMDDTHHMMSSZ.dump.gpg \
  --target-db kamilya_restore_drill \
  --yes
```

Остальные обязательные значения (`DB_*`, passphrase file, production DB name,
report directory и signing key) поступают только из root-only environment.
Команда проверяет companion checksum до decrypt, canonical UTC archive name,
RPO, структуру custom dump, пустоту target, Alembic head, pgvector, FORCE RLS и
агрегаты. Успех публикуется как JSON + проверенная detached GPG signature.
Plaintext хранится только во временном `0600` файле и удаляется trap независимо
от результата.

## Historical portable Supabase restore

`scripts/restore.sh` используется только для исторического dev/demo Supabase
archive формата `.dump.enc` и не является production success path. Такой archive
требует исключения platform-owned
`supabase_vault`/`vault` объектов и отдельной проверки RLS ролей.

Profile:

- исключает extension `supabase_vault`;
- исключает platform-owned table data schema `vault`;
- создаёт отсутствующую роль `lms_app` как `NOLOGIN`, чтобы восстановить
  RLS policies.

После restore оператор отдельно задаёт `LOGIN` и новый runtime password для
`lms_app`, обновляет `DATABASE_URL`, проверяет RLS/tenant context и только затем
подключает API/worker. Restore script намеренно не создаёт runtime password.

## Обязательная проверка restore

1. Alembic revision совпадает с repository head (`0120` на дату документа).
2. Количество public tables больше нуля.
3. Проверены агрегаты tenants, courses, enrollments и certificates.
4. `lms_app` существует; до provisioning он `NOLOGIN`.
5. Plaintext dump отсутствует после завершения.
6. RPO/RTO не превышают утверждённые `MAX_RPO_SECONDS`/`MAX_RTO_SECONDS`.
7. Report подписан drill signing key и подпись проверена до публикации.
8. Выполнены API migration check, tenant isolation gate и business smoke.
9. Одноразовая target DB и локальные копии удалены после фиксации результата.

## Последний подтверждённый drill

Последний исторический Supabase drill: 2026-07-27, Alembic `0078`. Он не
подтверждает текущий KZ production.

Последний KZ контрольный backup/restore на CT125: 2026-08-17. Encrypted
`*.dump.gpg` прошёл SHA-256 и `pg_restore --list`, service завершился успешно,
архив mode `0600`; актуальная schema на момент проверки — `0111`.

Перед следующим release требуется свежий disposable restore текущего archive с
текущим Alembic head. Новый fail-closed script и локальные contract tests не
являются таким operational proof. Нельзя считать предыдущий drill доказательством
после schema/release изменения.

Исторический drill содержал:

- Alembic `0078`;
- 56 public tables;
- данные LMS восстановлены;
- plaintext residue отсутствует;
- одноразовый контейнер и локальная копия удалены.

Агрегаты относятся к тестовым данным production-контура и не являются
бизнес-метриками.
