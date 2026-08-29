# Release Notes — [VERSION]

**Release date:** YYYY-MM-DD
**Product version:** [VERSION]
**Git tag:** v[VERSION]
**Deployed commit:** `<full-or-short-SHA>`

## Summary

One or two sentences describing the main outcome of this release for users.

## Added

-

## Changed

-

## Fixed

-

## Security

-

## Upgrade / deployment notes

- Database migrations: `alembic upgrade head` — required: yes/no; notes:
- Environment variables added/changed: none / list
- Frontend/backend deploy order:

## Verification

- Backend tests: `poetry run pytest` — result:
- Frontend tests: `pnpm test`, `pnpm typecheck`, `pnpm build` — result:
- Business smoke (user-visible flow checked):

## Rollback

Rollback plan: previous tag `v<X.Y.Z>`, redeploy steps, data caveats.

---

Usage: copy this file to a new file named after the release (for example
`v0.2.0.md`), replace every `[VERSION]` placeholder, and fill in each
section. Only the root orchestrator publishes and deploys a release.
