# Kamilya LMS — Project Context

> Living document. Askar: keep this updated when infra / repos / domains change.
> **No secrets in this file** — only references to where they're stored.

## Domains (Vercel)

| Domain | Purpose | Backend |
|---|---|---|
| `app.kml.kz` | LMS app (this monorepo — `apps/web` + `apps/api`) | Next.js 14 (Frankfurt `fra1`) |
| `www.kml.kz` / `kml.kz` | Marketing landing site (separate Next.js project) | Vercel Frankfurt, separate project |
| `cdn.lms.kml.kz` | Static assets (Supabase Storage CDN alias) | Supabase Storage |

The landing project is **NOT in this monorepo** — it's a separate Next.js project
imported into Vercel from a different source (GitLab / Vercel CLI / other).
Source repo not visible on GitHub `KamillaLMSCRM` org.

## Vercel projects

| Project | ID | Notes |
|---|---|---|
| LMS (`web`) | `prj_hJMzgp9QNFCwUMrsDEBZINpJJzBp` | Frankfurt, free plan, custom domain `app.kml.kz` |
| Landing | _(separate project, ID unknown)_ | Domain `www.kml.kz` |

Vercel aliases (legacy):
- `web-inky-three-48.vercel.app`
- `web-natt1inhm-kamillalmscrms-projects.vercel.app`

## Backend / infra

| Service | Where | Reference |
|---|---|---|
| API | Render — `kamilya-lms-api`, ID `srv-d8rp8ej7uimc73fglid0` (Frankfurt, free/starter, numInstances=1) | Render dashboard |
| DB | Supabase Postgres — project ref `ducegbxphkgffgozkchw`, pooler `aws-1-eu-central-1.pooler.supabase.com` | Supabase dashboard |
| Cache | Upstash Redis | Upstash dashboard |
| Storage | Supabase Storage, bucket `Kamilya LMS` (with space) | Supabase dashboard |
| LLM | Qwen 3.5 on local DGX, tunneled through VPS. `LLM_API_URL=http://10.66.66.7:8555` | Internal infra |
| Docling | `https://docling.kml.kz` (Vercel proxy) | Internal |

## Secrets / tokens — where they live

> Askar's rule: no production secrets in chat. Tokens are referenced, not stored, here.

| Token | Location (Windows Credential Manager name) | Notes |
|---|---|---|
| GitHub PAT — Kamilya-NEW (this monorepo) | `github-kamilya-new` | scope: `repo`, `read:org` |
| GitHub PAT — Landing site repo | `github-kamilya-landing` | separate repo, see Domain table |
| Render API | `render-kamilya-api` | service: `kamilya-lms-api` |
| Vercel — LMS project | `vercel-kamilya-lms` | project ID above |
| Vercel — Landing project | `vercel-kamilya-landing` | _TBD — Askar to provide when first needed_ |
| Supabase service role | `supabase-kamilya` | project ref above |
| Upstash Redis | `upstash-kamilya` | |
| LLM proxy auth | `qwen-dgx` | |
| Docling proxy | `docling-kml` | |

If a token isn't in Credential Manager yet, ask Askar — do not request a new
PAT if one already exists; reuse by reading the existing entry.

## GitHub org

- `KamillaLMSCRM` — single repo visible: `Kamilya-NEW` (this monorepo)
- Other repos (including landing) may exist on other Git hosts (GitLab etc.)

## Architectural conventions (per `AGENTS.md`)

- **Multi-tenancy is critical**: every query must filter by `tenant_id`.
- Direct SQL forbidden — ORM/repositories only. RLS enforced in Postgres.
- Passwords hashed with `argon2` (not bcrypt).
- No PII / JWT / passwords in logs.
- Backend: `apps/api/app/modules/<feature>/` modular monolith with
  `models.py` / `schemas.py` / `service.py` / `repository.py` / `router.py`.
- Frontend: feature-based (`apps/web/src/features/<feature>/`) +
  page routes in `apps/web/src/app/`.
- Design tokens in `apps/web/src/app/globals.css` (HSL channels) +
  `apps/web/tailwind.config.js` (semantic color aliases).

## Key URLs / routes (LMS)

Public: `/`, `/login`, `/login/demo`, `/register`, `/accept-invite`, `/kiosk/[token]`
Authed: `/dashboard`, `/courses`, `/courses/[id]`, `/courses/[id]/edit`,
        `/courses/quiz/[quizId]`, `/documents`, `/positions`, `/certificates`,
        `/settings`, `/my-courses`, `/my-quizzes`, `/student`, `/ai/generate`
Admin:  `/admin`, `/admin/users`, `/admin/employees`, `/admin/enrollments`,
        `/admin/kiosks`, `/admin/quizzes`, `/admin/quizzes/assign`, `/admin/staff`

## Languages

- `ru` (primary), `kk` (Kazakh — mandatory), `en` (secondary)
- Locale source of truth: `apps/web/src/i18n/locales/{ru,kk,en}.json`
- Currently client-side i18n via `localStorage` — **no URL `[locale]` segment**.
  This is intentional and matches what `apps/web` was built for. The landing
  site uses `[locale]` URL routing, which is why cross-link `app.kml.kz/ru/login`
  from landing 404s — landing link bug, not app bug.

## Important env-vars (Render / Vercel)

| Var | Where set | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Vercel | LMS → API base |
| `DATABASE_URL` | Render | Supabase pooler |
| `REDIS_URL` | Render | Upstash |
| `LLM_API_URL` | Render | `http://10.66.66.7:8555` |
| `DOCLING_URL` | Render | `https://docling.kml.kz` |
| `PUBLIC_URL` | Render | Default `https://app.kml.kz` — used for invite links |
| `ALLOW_ADMIN_DEMO` | Render | `true` enables `/login/demo` in prod. Askar usually keeps `false`. |

## Definition of done (per TZ §16)

See `TZ.md` §16. Atomic commits, conventional commits, tests ≥80% on
service/repository, i18n RU primary, tenant filters everywhere.

## Recent commits of note

- `9774247` — Design migration v2 (Sidebar/login/register/demo)
- `ea32bba` — Design migration v3 (full migration to semantic tokens)
- (next) `TBD` — UX fixes: progress banner, avatar dedupe, resilient polling
