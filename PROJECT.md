# Kamilya LMS Core

> Актуализировано: 2026-07-01.
> Статус: beta, продуктовый контур работает, продолжается доведение superadmin, RBAC и learner-flow.

## Видение Продукта

Kamilya LMS - корпоративная система обучения для компаний Казахстана. Система заменяет ручной onboarding и разрозненные курсы единым процессом:

1. Компания заводит tenant.
2. Админ tenant-а настраивает пользователей, интеграции, kiosk-ссылки и окружение.
3. Методолог управляет курсами, тестами, должностями, отделами и правилами назначения.
4. Обучающийся получает ссылку/доступ, проходит курсы и тесты.
5. Система автоматически выдает сертификат и сохраняет PDF.

Ключевая идея: LMS должна понимать оргструктуру. Курсы назначаются не только вручную, но и через правила "отдел -> курс", "должность -> курс", плюс ручное назначение конкретному обучающемуся.

## Роли И Границы

| Роль | Зона ответственности |
|---|---|
| `superadmin` | Платформа: tenant list, tenant state, global provider keys, platform diagnostics |
| `admin`, `org_admin` | Tenant-инфраструктура: настройки, интеграции, kiosk, системные пользователи |
| `methodologist`, `teacher` | Обучение: курсы, quiz, staff structure, правила, `/assignments` |
| `student` | Личный кабинет, прохождение курсов/тестов, сертификаты |

Принятые правила:

- Students не смешиваются с системными пользователями tenant-а.
- `/admin/team` - только команда администрирования/обучения tenant-а.
- `/assignments` - ручные назначения курсов обучающимся; это не admin-функция.
- `/admin/enrollments` - legacy redirect на `/assignments`.
- Tenant admin не определяет индивидуальные траектории обучения.
- Manual enrollment разрешен только для активных `student` того же tenant.

Канон RBAC: [docs/adr/0012-rbac-admin-vs-methodologist.md](./docs/adr/0012-rbac-admin-vs-methodologist.md).

## Learner Flow

1. Обучающийся открывает invite link `/accept-invite?token=...`.
2. После принятия приглашения `student` попадает на `/student`.
3. `/student`, `/my-courses`, `/my-quizzes` показывают назначенные курсы и quiz.
4. Course player не завершает курс, пока не закрыты уроки и обязательные quiz.
5. После успешного completion backend idempotent выдает сертификат.
6. Сертификаты доступны через `/certificates`; PDF хранится в Supabase Storage.

## Assignment Model

Источники назначения:

- `department` - через правила отдела.
- `position` - через правила должности.
- `manual` - прямое назначение через `/assignments`.

`enrollments` - runtime truth о том, какие курсы реально доступны обучающемуся. Rule tables являются источником пересчета, но UI обучающегося и сертификаты опираются на `enrollments`.

Manual removal разрешен только для `source='manual'`; rule-driven назначения удаляются через изменение правил и пересчет.

## Superadmin

Superadmin surface должен отвечать на вопрос "что происходит на платформе":

- список tenant-ов;
- active/total users;
- published/total courses;
- tenant details;
- platform/provider configuration.

Tenant list уже показывает фактические user/course counters. Дальше нужно довести tenant detail, impersonation и operational diagnostics.

## Техническая Архитектура

| Слой | Реализация |
|---|---|
| Frontend | Next.js 14 App Router, TypeScript, Tailwind |
| Backend | FastAPI, SQLAlchemy async, Alembic |
| DB | Supabase Postgres + pgvector |
| Storage | Supabase Storage, bucket `Kamilya LMS` |
| Queue | Upstash Redis |
| Worker | Celery на VPS как `kamilya-worker.service` |
| API hosting | Render service `kamilya-lms-api` |
| Web hosting | Vercel project `web` |
| AI | Qwen over DGX/VPS tunnel, DeepSeek/Voyage fallback |

## Database And Security

Runtime и migrations разделены:

- `DATABASE_URL` - runtime connection через `lms_app`, без `BYPASSRLS`.
- `MIGRATION_DATABASE_URL` - admin connection для Alembic DDL.

Supabase на 2026-07-01:

- Alembic version: `0040`.
- Tenant tables with `tenant_id`: RLS enabled and FORCE RLS enabled.
- `provider_keys` исключена из общей tenant policy, потому что `tenant_id IS NULL` используется для global platform key.
- Production Render и VPS worker обновлены на `lms_app` runtime connection.

Подробности: [docs/supabase-audit-2026-07-01.md](./docs/supabase-audit-2026-07-01.md).

## Production Infra

| Компонент | Где |
|---|---|
| Frontend | `https://app.kml.kz` on Vercel |
| Backend | `https://kamilya-lms-api.onrender.com` on Render |
| DB | Supabase pooler `aws-1-eu-central-1.pooler.supabase.com` |
| Storage | Supabase Storage bucket `Kamilya LMS` |
| Worker | VPS `173.249.51.164`, systemd `kamilya-worker` |
| Docling | VPS service behind `docling.kml.kz` |
| WhatsApp gateway | VPS service behind `wa.kml.kz` |

`api.kml.kz` не является production API source of truth; production API сейчас Render URL.

## Документация

- Product/current state: this file and [docs/PROJECT-CONTEXT.md](./docs/PROJECT-CONTEXT.md)
- Deployment: [DEPLOY.md](./DEPLOY.md)
- VPS: [docs/VPS_CONNECTION_GUIDE.md](./docs/VPS_CONNECTION_GUIDE.md)
- RBAC: [docs/adr/0012-rbac-admin-vs-methodologist.md](./docs/adr/0012-rbac-admin-vs-methodologist.md)
- RLS/app role: [docs/adr/0004-rls-force-and-app-role.md](./docs/adr/0004-rls-force-and-app-role.md)
- Supabase audit: [docs/supabase-audit-2026-07-01.md](./docs/supabase-audit-2026-07-01.md)
- Tenant registration/trial: [docs/product/tenant-registration-trial-flow.md](./docs/product/tenant-registration-trial-flow.md)

Old audits and large TZ files remain historical/spec references. Short completed plans should be removed once their result is reflected here or in ADR/audit docs.
