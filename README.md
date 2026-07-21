# Kamilya LMS

AI-first корпоративная LMS для обучения сотрудников в multi-tenant SaaS модели.

Production:

- Frontend: https://app.kml.kz
- Backend API: https://kamilya-lms-api.onrender.com
- DB: Supabase Postgres, project `ducegbxphkgffgozkchw`
- Storage: Supabase Storage, bucket `Kamilya LMS`
- Worker/VPS: `kamilya-worker` на `173.249.51.164`

## Что Это

Kamilya LMS закрывает цикл корпоративного обучения:

1. Методолог загружает документы, должностные инструкции или создает курс вручную.
2. AI помогает собрать курс, уроки, кейсы и тесты.
3. Методолог публикует курс и назначает его через правила отдела/должности или вручную через `/assignments`.
4. Обучающийся получает приглашение, входит в личный кабинет, проходит уроки и тесты.
5. После выполнения требований система выдает сертификат и хранит PDF в Supabase Storage.

Продуктовая модель строго разделяет роли:

- `superadmin` управляет платформой и tenant-ами.
- `admin` / `org_admin` управляют tenant-инфраструктурой, настройками, интеграциями и системными пользователями.
- `methodologist` управляет штатной структурой, курсами, тестами, правилами назначения и ручными назначениями.
- `student` только проходит обучение и получает сертификаты.

## Текущее Состояние

Актуально на 2026-07-21:

- `/admin/team` показывает только системных пользователей tenant-а, без студентов.
- `/admin/enrollments` является legacy URL и редиректит на `/assignments`.
- `/assignments` принадлежит learning-content домену и доступен `methodologist`.
- Backend manual enrollments принимает только активных `student` в текущем tenant.
- Learner flow ведет `student` на `/student`, а не на admin/dashboard экран.
- Course completion требует завершенные уроки и пройденные quiz, затем idempotent выдает сертификат.
- Supabase schema обновлена до Alembic `0068`.
- Runtime `DATABASE_URL` использует `lms_app` без `BYPASSRLS`.
- `MIGRATION_DATABASE_URL` отделен от runtime URL и используется Alembic для DDL-миграций.
- Tenant registration доступен на `/register-tenant`; email OTP login работает через Resend (`no-reply@notify.kml.kz`).
- Source-governance backend revision `5bc86c6` развёрнута; корневой `GET/HEAD /`, `/health` и `/api/v1/health` возвращают 200.
- Первый production smoke полного tenant-flow пройден: AI course generation, assignment, learner completion, certificate `KML-2026-5DE383`.
- Документы разных тематик не смешиваются автоматически: backend требует выбрать thematic cluster либо явно указать общую учебную цель.
- Для курса и уроков сохраняются source provenance и статус проверки после ручного редактирования.

## Архитектура

```text
apps/web  -> Next.js 14, Vercel, app.kml.kz
apps/api  -> FastAPI, Render, kamilya-lms-api.onrender.com
DB        -> Supabase Postgres + pgvector
Storage   -> Supabase Storage bucket "Kamilya LMS"
Queue     -> Valkey TLS on VPS
Worker    -> Celery systemd service on VPS, AI/ingestion/apply-rules
AI        -> Qwen via DGX/VPS tunnel, DeepSeek/Voyage fallback
```

## Основные Документы

| Документ | Назначение |
|---|---|
| [PROJECT.md](./PROJECT.md) | Актуальное описание продукта и архитектуры |
| [docs/CODEX_HANDOFF.md](./docs/CODEX_HANDOFF.md) | Точка входа при переносе на другой компьютер или новую задачу Codex |
| [docs/PROJECT-CONTEXT.md](./docs/PROJECT-CONTEXT.md) | Живой контекст infra, ролей, URL и env |
| [docs/USER_DOCUMENTATION_RU.md](./docs/USER_DOCUMENTATION_RU.md) | Каноническое руководство пользователя |
| [docs/adr/0012-rbac-admin-vs-methodologist.md](./docs/adr/0012-rbac-admin-vs-methodologist.md) | Канон RBAC admin vs methodologist |
| [docs/supabase-audit-2026-07-01.md](./docs/supabase-audit-2026-07-01.md) | Supabase/RLS/runtime cutover audit |
| [docs/VPS_CONNECTION_GUIDE.md](./docs/VPS_CONNECTION_GUIDE.md) | VPS services and access model |
| [DEPLOY.md](./DEPLOY.md) | Production deployment runbook |
| [AGENTS.md](./AGENTS.md) | Правила для AI-агентов |
| [docs/LESSONS.md](./docs/LESSONS.md) | Накопленные lessons learned |

`docs/plans/` используется только для активных планов. Выполненные короткие планы не должны оставаться отдельным ТЗ, если их результат уже закреплен в `PROJECT.md`, ADR или audit docs.

## Dev Quickstart

```powershell
cd apps\api
poetry install --with dev

cd ..\web
npm install
npm run dev
```

Локальные секреты лежат в `.env`; файл игнорируется git. Не переносить секреты в docs, `render.yaml`, markdown или commit history.

## Проверки

Backend:

```bash
cd apps/api
poetry run python -m compileall app tests
poetry run pytest tests -q
poetry run alembic current
```

Frontend:

```powershell
cd apps/web
.\node_modules\.bin\tsc.cmd --noEmit
.\node_modules\.bin\vitest.cmd run
.\node_modules\.bin\next.cmd build
```

DB-dependent suite требует доступный PostgreSQL/pgvector test DB; отсутствие БД нужно отмечать как непроверенную интеграцию, а не как успешный test run.
