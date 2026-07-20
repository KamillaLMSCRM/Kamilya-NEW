# Cleanup, push and deployment verification

**Date:** 2026-07-20
**Scope:** reconcile the local worktree, publish reviewed changes to `master`, and verify Render/Vercel production deployments.

## Checklist

- [x] Separate HostKZ migration and validation work from product changes.
- [x] Ignore local tenant documents, archives, and runtime storage.
- [ ] Commit the course release integrity changes after tests and secret checks.
- [ ] Preserve useful historical QA and pilot documentation in a docs-only commit.
- [ ] Push to `origin/master` using the repository token without Git Credential Manager.
- [ ] Verify Render deployment, API health, and production Alembic revision.
- [ ] Verify Vercel deployment and `app.kml.kz` availability.

## Safety boundaries

- Do not delete or commit local tenant source documents.
- Do not print values from `.env`.
- Keep Supabase active; HostKZ remains a pilot environment.
- Treat deployment as complete only after both provider status and public endpoint checks pass.
