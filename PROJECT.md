# Kamilya LMS Core

> Актуализировано: 2026-07-21.
> Статус: beta, первый production tenant-flow пройден end-to-end; trial limits, управление источниками AI-курса и фоновые задачи работают в production. Billing и полный commercial control суперадмина остаются незавершёнными.

## Видение Продукта

Kamilya LMS - корпоративная система обучения для компаний Казахстана. Система заменяет ручной onboarding и разрозненные курсы единым процессом:

1. Компания заводит tenant.
   Self-service trial registration уже доступна через `/register-tenant`: HR оставляет данные компании, tenant создается в `trial` статусе, первый пользователь получает роль `admin`.
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
| `methodologist` | Обучение: курсы, тесты, штат, должности, правила, назначения и журнал обучения |
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

## AI Courses And Source Governance

Обычный AI-курс создаётся только из выбранных документов tenant-а:

1. После выбора документов система проверяет их тематическую совместимость по embeddings.
2. Однородный набор используется целиком. Неоднородный набор делится на тематические группы.
3. Методолог выбирает одну группу либо явно объединяет группы и формулирует общую учебную цель.
4. Backend повторяет проверку до списания trial-лимита и постановки Celery-задачи.
5. Для каждого урока сохраняются документы и фрагменты-источники.
6. При отсутствии релевантного материала генерация останавливается; общие знания LLM не подмешиваются.
7. Ручное изменение урока требует новой проверки источников или явного одобрения методологом.

Миграция `0068` хранит source strategy и анализ на курсе, а provenance и validation status — на уроках. Подробности: [управление источниками AI-курса](./docs/plans/done/2026-07-21_document-source-governance.md).

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
| Queue/cache | Valkey на VPS, TLS `6380`, AOF и `noeviction` |
| Worker | Celery на VPS как `kamilya-worker.service`; AI, ingestion и apply-rules tasks |
| API hosting | Render service `kamilya-lms-api` |
| Web hosting | Vercel project `web` |
| AI | Qwen over DGX/VPS tunnel, DeepSeek/Voyage fallback |

## Database And Security

Runtime и migrations разделены:

- `DATABASE_URL` - runtime connection через `lms_app`, без `BYPASSRLS`.
- `MIGRATION_DATABASE_URL` - admin connection для Alembic DDL.

Supabase на 2026-07-21:

- Alembic version: `0068`.
- Tenant tables with `tenant_id`: RLS enabled and FORCE RLS enabled.
- `provider_keys` исключена из общей tenant policy, потому что `tenant_id IS NULL` используется для global platform key.
- Production Render и VPS worker обновлены на `lms_app` runtime connection.

## Auth And Tenant Acquisition

- `/login` поддерживает два режима: email OTP и Telegram code flow.
- Email OTP: `POST /api/v1/auth/email/request-code` и `POST /api/v1/auth/email/verify-code`.
- Production transactional email: Resend, sender `Kamilya LMS <no-reply@notify.kml.kz>`.
- Resend sending domain: `notify.kml.kz`; DKIM/SPF/return-path/DMARC verified in DNS as of 2026-07-02.
- `/register-tenant` создает trial tenant: 14 дней, 1 normal AI course, 1 job-instruction course, 10 learners, 3 system users.
- Billing UI и superadmin lead management не завершены. Trial limits (количество и окончание периода) enforced на backend; login/dashboard остаются доступны для upgrade/support. См. `docs/NEXT_STEPS_2026-07-01.md`.

Production evidence:

- AI job: `64891564-5bb5-4648-ba40-c3ec04d40621`.
- Generated course: `7e434b25-1057-42b0-ac64-ed56daa6b041`.
- Certificate issued: `KML-2026-5DE383`.
- Source-governance backend revision: `5bc86c6`; production DB revision: `0068`.
- Release gate: backend `356 passed`, frontend `41 passed`, typecheck/build passed, GitHub Actions `29820432047` succeeded.

Подробности: [docs/supabase-audit-2026-07-01.md](./docs/supabase-audit-2026-07-01.md).

## Production Infra

| Компонент | Где |
|---|---|
| Frontend | `https://app.kml.kz` on Vercel |
| Backend | `https://kamilya-lms-api.onrender.com` on Render |
| DB | Supabase pooler `aws-1-eu-central-1.pooler.supabase.com` |
| Storage | Supabase Storage bucket `Kamilya LMS` |
| Queue/cache | Valkey on VPS `173.249.51.164`, TLS `6380` |
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
- User guide: [docs/USER_DOCUMENTATION_RU.md](./docs/USER_DOCUMENTATION_RU.md)
- Methodologist release guide: [docs/methodologist-course-release-guide-ru.md](./docs/methodologist-course-release-guide-ru.md)

Old audits and large TZ files remain historical/spec references. Short completed plans should be removed once their result is reflected here or in ADR/audit docs.
