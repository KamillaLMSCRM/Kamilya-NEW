# Kamilya LMS: handoff для следующего Codex

**Обновлено:** 2026-09-07
**Рабочая папка:** `C:\Kamilya New\Kamilya-NEW`
**Репозиторий:** `KamillaLMSCRM/Kamilya-NEW`, branch `master`

## Сначала прочитать

1. [`AGENTS.md`](../AGENTS.md)
2. [`ERRORS.md`](../ERRORS.md)
3. [`PROJECT.md`](../PROJECT.md)
4. [`PROJECT-CONTEXT.md`](PROJECT-CONTEXT.md)
5. [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md)
6. [`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md)
7. [`PROJECT_INTERNAL_DOCUMENTATION.md`](PROJECT_INTERNAL_DOCUMENTATION.md)
8. [`BACKUP_RESTORE_RUNBOOK.md`](BACKUP_RESTORE_RUNBOOK.md)
9. [`PRODUCTION_FRONTEND_RUNBOOK.md`](PRODUCTION_FRONTEND_RUNBOOK.md)

Не использовать старые commit reports, ТЗ и переписку как описание текущего
production. Они удалены из рабочего дерева и при необходимости доступны в Git
history.

## Текущее состояние

| Контур | Состояние |
|---|---|
| Canonical Git branch | `KamillaLMSCRM/Kamilya-NEW`, `master`; exact remote SHA всегда читать заново |
| Production frontend | CT137 `webkml` на Proxmox node `pve3`; native Next.js/OpenRC/Nginx без Docker |
| Frontend ingress | `app.kml.kz` -> Cloudflare DNS-only `92.38.49.167` -> KZ proxy/WireGuard -> CT137 |
| Frontend release readback | exact SHA `e463527cd8f5e67e987c44d8d769f337714bd25f`; `/healthz` и `/login` HTTP 200 после переноса CT137 с `pve2` на `pve3` |
| Production API/workers | VM126 в KZ-контуре; public API `https://api.kml.kz/api`; current health exact SHA проверять перед каждым release |
| Production DB | Native PostgreSQL 17 + pgvector на CT125, private-only; текущую Alembic revision читать отдельно |
| Dev/demo | Vercel `kamilya-lms-dev`, Render и Supabase DEV/test; не production |
| Frontend rollback | Vercel project `web`, сохранённый CNAME и Proxmox snapshot; не текущий runtime |
| Public landing | `kml.kz`/`www.kml.kz` на CT137 через KZ proxy; native Next.js service `kamilya-landing`, exact source SHA `e70534f4814fd743edef16363d7393361fe874c7` |

Технический P0 и прикладной synthetic tenant journey закрыты. Перед
подключением конкретного клиента остаются только условные gates для реально
заявляемых SCORM/kiosk/KZ-data/capacity возможностей. Подробности:
  [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md). Точные CI, worker, DB,
backup и monitoring states не копировать из старого handoff: читать их заново
из production и канонического реестра.

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
- `apps/web`: Next.js 15.5.23, React, TypeScript.
- Production frontend: CT137, native Node.js/OpenRC/Nginx, без Docker.
- Production DB: PostgreSQL 17 + pgvector на CT125; Supabase — dev/test.
- Queue/cache and workers: Valkey и Celery на VM126.
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
- В `.env` есть именованные пути доступа к production/dev providers и
  инфраструктуре. Использовать только target-specific credential согласно
  `PROJECT-CONTEXT.md`, не перебирать значения и не выводить их.
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
pnpm test
pnpm typecheck
$env:NEXT_TELEMETRY_DISABLED='1'
pnpm build
```

Перед release:

1. проверить worktree;
2. прогнать focused tests и полный suite по риску;
3. проверить migration head;
4. push в `master`;
5. дождаться CI;
6. проверить exact frontend runtime SHA на CT137, API/worker image и DB revision
   независимо; Vercel/Render проверять только для dev или выбранного rollback;
7. пройти public и role-specific production smoke.

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
2. Для CT137 использовать подтверждённый restricted key-only path через
   proxy/WireGuard; Proxmox console оставлять только bootstrap/recovery путём.
   Landing deploy допускается только через exact root-owned helper; общий sudo,
   парольный SSH и размещение runtime на proxy запрещены.
3. Брать следующий P1 из `PRODUCT_BACKLOG.md` по одному
   каноническому workflow.
4. Любое изменение UI обновляет пользовательское руководство.
5. Любое долговечное архитектурное решение получает ADR.
