# Kamilya LMS - Project Context

> Living document. No secrets in this file.
> Updated: 2026-07-21.

## Source Of Truth

| Area | Source |
|---|---|
| Product/current behavior | `PROJECT.md` |
| RBAC admin vs methodologist | `docs/adr/0012-rbac-admin-vs-methodologist.md` |
| Supabase/RLS/runtime cutover | `docs/supabase-audit-2026-07-01.md` |
| VPS services | `docs/VPS_CONNECTION_GUIDE.md` |
| Deployment | `DEPLOY.md` |
| Tenant registration/trial | `docs/product/tenant-registration-trial-flow.md` |
| User workflows | `docs/USER_DOCUMENTATION_RU.md` |
| AI course release | `docs/methodologist-course-release-guide-ru.md` |
| Source governance release record | `docs/plans/done/2026-07-21_document-source-governance.md` |
| Agent rules | `AGENTS.md` |

## Repositories

| Repo | Purpose |
|---|---|
| `KamillaLMSCRM/Kamilya-NEW` | Main LMS monorepo |
| `KamillaLMSCRM/kamilya-landing` | Separate marketing site, private |

Local current checkout in this session:

```text
C:\Kamilya New\Kamilya-NEW
```

## Domains And Services

| Service | URL / ID | Notes |
|---|---|---|
| Frontend app | `https://app.kml.kz` | Vercel, Next.js |
| Marketing | `https://www.kml.kz` | Separate landing repo |
| Backend API | `https://kamilya-lms-api.onrender.com` | Render service `srv-d8rp8ej7uimc73fglid0` |
| Transactional email | Resend, `no-reply@notify.kml.kz` | `EMAIL_PROVIDER=resend`; domain `notify.kml.kz` |
| DB | Supabase project `ducegbxphkgffgozkchw` | Pooler `aws-1-eu-central-1.pooler.supabase.com` |
| Storage | Supabase bucket `Kamilya LMS` | Certificates and files |
| Queue/cache | VPS `173.249.51.164`, Valkey TLS `6380` | Celery broker/result backend, OTP, rate limits and progress |
| Worker | VPS `173.249.51.164`, `kamilya-worker.service` | Celery AI, ingestion and apply-rules tasks |
| Docling | `docling.kml.kz` | VPS service |
| WhatsApp gateway | `wa.kml.kz` | VPS service |

`api.kml.kz` is not the production API source of truth. Use the Render URL unless DNS is intentionally changed.

## Roles

| Role | Product meaning |
|---|---|
| `superadmin` | Platform operator, tenant-level oversight |
| `admin`, `org_admin` | Tenant infrastructure, integrations, team/system users |
| `methodologist` | Learning content, staff/course rules, assignments |
| `student` | Learner only |

Important route ownership:

- `/admin/team` - tenant system users only.
- `/admin/super/*` - platform/superadmin.
- `/admin/staff` - staff structure, rules, imports.
- `/assignments` - direct learner-course assignment for `methodologist`.
- `/admin/enrollments` - legacy redirect to `/assignments`.
- `/student`, `/my-courses`, `/my-quizzes`, `/certificates` - learner surfaces.

## Env Model

Backend runtime:

```env
DATABASE_URL=...lms_app...
MIGRATION_DATABASE_URL=...postgres...
REDIS_URL=...
SUPABASE_URL=...
SUPABASE_KEY=...
SUPABASE_BUCKET=Kamilya LMS
STORAGE_BACKEND=supabase
PUBLIC_URL=https://app.kml.kz
EMAIL_PROVIDER=resend
RESEND_API_KEY=...
EMAIL_FROM=Kamilya LMS <no-reply@notify.kml.kz>
```

Rules:

- `DATABASE_URL` must use `lms_app` without `BYPASSRLS`.
- `MIGRATION_DATABASE_URL` is used by Alembic for schema changes.
- Render and VPS worker both need the same DB URL split.
- `.env` is ignored by git and may contain secrets.
- Do not copy secrets into docs or chat.
- `RESEND_API_KEY` is backend-only and currently set in Render env.

Frontend:

```env
NEXT_PUBLIC_API_URL=https://kamilya-lms-api.onrender.com/api
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

## Current Production DB State

As of 2026-07-21:

- Production Supabase schema and repository head: `0068`.
- RLS/FORCE RLS enabled for tenant-scoped tables with `tenant_id`.
- Runtime app and worker connect as `lms_app`.
- `provider_keys` is intentionally excluded from generic tenant RLS migration because `tenant_id IS NULL` represents global platform keys.

Job-instruction source model:

- `documents.category` distinguishes `general` and `job_instruction` sources;
- `positions.instruction_document_id` points to the current instruction;
- `courses.source_instruction_id` and `source_instruction_version_at` preserve course provenance;
- the source file is stored through the configured storage backend and downloaded through a tenant-scoped API;
- generation uses a separate `jd_course_generations_used` trial counter.

Ordinary AI course source model:

- selected documents are checked by `POST /api/v1/ai/document-compatibility` before generation;
- mixed source sets require selecting one cluster or an intentional-combination goal;
- courses persist selected sources, strategy, goal and compatibility analysis;
- lessons persist source documents, retrieved references and validation status;
- manual lesson edits require renewed source review before release;
- content generation does not fall back to general LLM knowledge when relevant source chunks are absent.

## Current Production Deploy

As of 2026-07-21:

- GitHub `master`: `2545eb3 fix(ci): align Poetry runtime dependencies`.
- Render service `srv-d8rp8ej7uimc73fglid0` runs backend revision `5bc86c6`; later master commits are documentation and CI dependency metadata only.
- Render runs `PYTHONPATH=. alembic upgrade head` as a pre-deploy command from `apps/api`.
- Production PostgreSQL is at Alembic revision `0068`.
- Vercel production deployment for `app.kml.kz` is green on the source-governance frontend revision.
- `/`, `/health`, and `/api/v1/health` return 200.
- Email OTP request endpoint returns a neutral success response for unknown emails and sends OTP for known tenant users.
- First tenant-flow production smoke passed: AI course generation, assignment, learner completion and certificate issue.
- Smoke evidence: AI job `64891564-5bb5-4648-ba40-c3ec04d40621`, course `7e434b25-1057-42b0-ac64-ed56daa6b041`, certificate `KML-2026-5DE383`.
- Source-governance release gate passed: backend `356 passed`, frontend `41 passed`, frontend typecheck/build passed, and GitHub Actions run `29820432047` succeeded.
- VPS Celery worker is active on revision `5bc86c6` with `ai.generate_course`, `ai.ingest_document` and `positions.apply_course_rules` registered.
- Production had no successfully indexed documents at release time, so semantic clustering was verified against real local PostgreSQL/pgvector rather than existing production content.

## Tenant Acquisition Status

Implemented:

- `/register-tenant` self-service trial registration.
- Trial storage: `tenant_leads`, `tenant_usage`, and trial fields on `tenants`.
- Email OTP login with Resend provider support.

Implemented:

- Backend enforcement количественных trial limits и окончания trial-периода для tenant-scoped операций.
- AI generation dispatch через Celery/Redis; production worker должен быть поднят и мониториться.

Not finished:

- Trial onboarding wizard.
- Billing/upgrade request UI.
- Superadmin lead pipeline and tenant activation workflow.
- Cleanup for historical queued/running AI jobs from pre-fix smoke runs.

## Product Invariants

- Students are never mixed into tenant admin team management.
- System users and learners are different product concepts even if both are rows in `users`.
- Direct manual assignment is learning-content work, not tenant-admin work.
- Course completion must require lessons and required quiz checks.
- Empty generated quiz records must not block course completion.
- AI generation must not block indefinitely on optional LLM review.
- Documents from unrelated subject areas must not be silently mixed into one AI course.
- Generated lessons must remain traceable to the selected tenant documents.
- Missing source material must stop grounded generation instead of invoking general LLM knowledge.
- Manual lesson edits invalidate automatic source verification until regeneration or explicit methodologist approval.
- Certificate issue is backend-owned and idempotent.
- Tenant filtering and RLS are mandatory for tenant-scoped data.

## Documentation Hygiene

- Keep `PROJECT.md` and this file current after product/infra changes.
- Keep ADRs for durable decisions.
- Keep large `TZ_*` files only while they are still active specs or referenced by code/ADR.
- Remove completed short `docs/plans/*` files once outcomes are reflected in product docs.
