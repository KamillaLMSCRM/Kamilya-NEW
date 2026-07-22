# Cleanup, push and deployment verification

**Date:** 2026-07-20
**Scope:** reconcile the local worktree, publish reviewed changes to `master`, and verify Render/Vercel production deployments.

## Checklist

- [x] Separate HostKZ migration and validation work from product changes.
- [x] Ignore local tenant documents, archives, and runtime storage.
- [x] Commit the course release integrity changes after tests and secret checks.
- [x] Preserve useful historical QA and pilot documentation in a docs-only commit.
- [x] Push to `origin/master` using the repository token without Git Credential Manager.
- [x] Fix the production-schema drift found while applying migration `0065`.
- [x] Synchronize the Render pre-deploy migration command with `render.yaml`.
- [x] Verify Render deployment, API health, and production Alembic revision.
- [x] Verify Vercel deployment and `app.kml.kz` availability.

## Safety boundaries

- Do not delete or commit local tenant source documents.
- Do not print values from `.env`.
- Keep Supabase active; HostKZ remains a pilot environment.
- Treat deployment as complete only after both provider status and public endpoint checks pass.

## 2026-07-22 release attempt — blocked before deployment

**Target:** local `master` commit `2a76e063e03d88c098eee98c006d1ad3aa3268d9` (`fix: harden tenant auth role policy and release gates`).

**Evidence:** local `master` is one commit ahead of `origin/master`. The HTTPS remote is `https://github.com/KamillaLMSCRM/Kamilya-NEW.git`; the existing Windows Git Credential Manager identity was already observed to receive HTTP 403 for this repository. No GitHub CLI authentication is available. SSH has no discovered key or agent and `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -T git@github.com` returned `Permission denied (publickey)`.

**Decision:** no authorized push path exists in this environment. The target commit and this report remain local; no Render, Vercel, VPS/Celery, Supabase, or DNS action was taken because deploying an unpushed revision is prohibited.

**Status:** blocked pending an authorized GitHub write credential or repository access for the configured account.

## 2026-07-22 production release evidence — target published and deployed

**Target:** `2a76e063e03d88c098eee98c006d1ad3aa3268d9`. The earlier Git credential blocker is resolved: `origin/master` now equals the target.

**Providers and database:**

- Vercel deployment `dpl_29TvH16dgLdaDiCgJ5zQqTp8om9e` is `READY`, records the exact target SHA, and `https://app.kml.kz` returned HTTP 200.
- Render deployment `dep-d9g5lgernols73a42tng` is `live` at the exact target SHA. `https://kamilya-lms-api.onrender.com/api/v1/health` returned 200 with the expected health payload.
- The Supabase `alembic_version` read returned revision `0068` (the deployed Alembic head).

**Worker:**

- The VPS worker was safely fast-forwarded from `5bc86c61591bc4bea849b7700a70ef7efd4a27ee` to the target. Its only pre-existing dirty entries were two untracked, non-generated `.env` backup files; neither conflicts with the target nor is open by the worker. Both remain intact.
- The worker systemd unit uses `/opt/kamilya-worker/apps/api/.venv` and `app.core.celery_app:celery_app`. The target’s newly declared packages were reconciled with that venv's `pip`; `pip check` and imports passed before restart.
- Poetry 2.4.1 on the VPS reports its lock diagnostic although the local Poetry 1.8.5 validation reports the exact target is valid; no lock file was created or changed. The target does not track `apps/api/poetry.lock` on the VPS.
- After restart: worker Git SHA equals the target, tracked worktree is clean, service is active, Celery ping succeeds, and `ai.generate_course`, `ai.ingest_document`, and `positions.apply_course_rules` are registered.

**Read-only user-flow evidence:**

- Superadmin login and refresh both returned 200.
- Impersonated `admin`, `org_admin`, and `methodologist` each received 200 from the tenant-scoped training-log summary. An admin received 403 from AI jobs as required.
- A public WebSocket attempt with the admin token closed abnormally (1006) rather than returning the expected application 4003 close code. No AI job was created and multi-poll/RLS WebSocket behavior remains unverified; this must be investigated before treating that portion of the release gate as complete.

**Status:** provider revisions, database revision, API/frontend availability, worker revision, and the listed HTTP authorization checks are verified. The WebSocket authorization/multi-poll gate remains incomplete.
