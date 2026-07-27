# Kamilya LMS: handoff для следующего Codex

**Обновлено:** 2026-07-27
**Рабочая папка:** `C:\Kamilya New\Kamilya-NEW`
**Репозиторий:** `KamillaLMSCRM/Kamilya-NEW`, branch `master`

## Сначала прочитать

1. [`AGENTS.md`](../AGENTS.md)
2. [`PROJECT.md`](../PROJECT.md)
3. [`PROJECT-CONTEXT.md`](PROJECT-CONTEXT.md)
4. [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md)
5. [`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)
6. [`PROJECT_INTERNAL_DOCUMENTATION.md`](PROJECT_INTERNAL_DOCUMENTATION.md)
7. [`LESSONS.md`](LESSONS.md)
8. [`BACKUP_RESTORE_RUNBOOK.md`](BACKUP_RESTORE_RUNBOOK.md)

Не использовать старые commit reports, ТЗ и переписку как описание текущего
production. Они удалены из рабочего дерева и при необходимости доступны в Git
history.

## Текущее состояние

| Контур | Состояние |
|---|---|
| Проверенный application baseline | `a10786c6d2c0b4cfa31385e7613d6390452c32cd`; актуальный docs HEAD проверять через `git rev-parse HEAD` |
| CI | success, run `30262132014` |
| Production smoke | GitHub run `30262131946` success; полный synthetic tenant journey также passed |
| Vercel | production `READY`, deploy `dpl_DtsUxvR2ChbkKHv3RWRaXCr5yZSg`, commit `a10786c` |
| Render API | live, deploy `dep-d9jk39b7uimc739ohgjg`, commit `a10786c` |
| Production DB | Alembic `0078`, совпадает с repository head |
| Celery worker | active/enabled, commit `a10786c`, Celery ping passed |
| Backup | encrypted daily timer active; real backup and restore drill passed |
| Monitoring | VPS watchdog and GitHub production smoke active |

Технический P0 и прикладной synthetic tenant journey закрыты. Перед
подключением конкретного клиента остаются только условные gates для реально
заявляемых SCORM/kiosk/KZ-data/capacity возможностей. Подробности:
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

## Продуктовая модель

Kamilya LMS:

```text
документы компании
  -> ingestion/AI
  -> курс и тест
  -> публикация
  -> правило или ручное назначение
  -> обучение
  -> тест
  -> сертификат
  -> журнал обучения
```

### Роли

- `superadmin`: платформа и tenants;
- `admin`: организация tenant, системные пользователи, интеграции;
- `methodologist`: контент, сотрудники, правила, назначения и результаты;
- `student`: обучение.

`teacher` и `org_admin` удалены. Не восстанавливать их для обратной
совместимости: реальных пользователей этих ролей нет.

Один пользователь может иметь несколько ролей, но использует одну active role.
Не объединять capability всех ролей.

### Канонические поверхности

- `/admin/team`: только системная команда tenant;
- `/staff`: сотрудники, структура, импорт;
- `/training-rules`: правила организации/отделов/должностей;
- `/positions`: должность, инструкция и профиль квалификации;
- `/assignments`: ручное назначение;
- `/training-log`: прохождение и доказательства;
- `/documents`: библиотека источников;
- `/ai/generate`: генерация с выбранными источниками.

Tenant admin не занимается курсами, тестами, обучающимися и назначениями.

## Техническая архитектура

- `apps/api`: FastAPI, SQLAlchemy async, Alembic, PostgreSQL/pgvector.
- `apps/web`: Next.js 14, React, TypeScript.
- DB/storage: Supabase production.
- Queue/cache: Valkey TLS на VPS.
- Worker: Celery на VPS.
- Email: Resend.
- Document conversion: Docling.
- AI jobs: Celery; provider fallback определяется модулем.

Tenant isolation требует одновременно:

1. `tenant_id`;
2. backend ownership checks;
3. RLS policy;
4. FORCE RLS;
5. runtime DB role без `BYPASSRLS`;
6. cross-tenant test.

## Локальные секреты

- Файл: `.env` в корне репозитория.
- Файл игнорируется Git.
- Значения не печатать в чат, docs или test output.
- В `.env` есть доступы к production DB, Render, Vercel, GitHub, Supabase,
  Resend и VPS.
- Перед добавлением переменной сверять `.env.example`.

## Проверки

Backend:

```powershell
cd "C:\Kamilya New\Kamilya-NEW\apps\api"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m alembic heads
```

Frontend:

```powershell
cd "C:\Kamilya New\Kamilya-NEW\apps\web"
npm test
npm run typecheck
$env:NEXT_TELEMETRY_DISABLED='1'
npx next build
```

Перед release:

1. проверить worktree;
2. прогнать focused tests и полный suite по риску;
3. проверить migration head;
4. push в `master`;
5. дождаться CI;
6. проверить Vercel, Render, worker и DB revision независимо;
7. пройти production smoke.

HTTP health не доказывает, что worker, migrations и пользовательский flow
актуальны.

## Git

- Commit author: `kamilla_lms_crm@proton.me`.
- Push выполнять токеном из `.env`, без Git Credential Manager.
- Не коммитить `.env`, Playwright artifacts и локальные outputs.
- Не откатывать чужие незакоммиченные изменения.
- История выполненных работ хранится в Git, а не в папке с устаревшими
  финальными отчётами.

## Следующий порядок работ

1. Сверить release parity с `PRODUCTION_READINESS.md`.
2. Пройти клиентскую приёмку на отдельном tenant с его реальными документами.
3. После первого tenant брать P1 из `PRODUCT_BACKLOG.md` по одному
   каноническому workflow.
4. Любое изменение UI обновляет пользовательское руководство.
5. Любое долговечное архитектурное решение получает ADR.
