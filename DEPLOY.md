# Kamilya LMS production deployment

This entrypoint describes the current KZ production contour. Exact release
identity, open gates and accepted evidence live in
[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md); environment and
access ownership live in
[`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md).

## Current topology

| Component | Production runtime |
|---|---|
| Public application | `https://app.kml.kz`; Cloudflare DNS-only -> KZ proxy -> WireGuard -> CT137 |
| Public landing | `https://kml.kz` / `https://www.kml.kz`; KZ proxy -> WireGuard -> separate native Next.js service on CT137 |
| Frontend | Native Next.js/OpenRC/Nginx on CT137 `webkml`, without Docker |
| API | `https://api.kml.kz/api`; KZ proxy -> WireGuard -> VM126 FastAPI |
| Workers and queue | Three Celery workers plus Valkey on VM126; API and workers must use one exact image/SHA |
| Database | Private-only PostgreSQL 17 + pgvector on CT125 |
| File runtime | Shared API/worker storage on VM126 with encrypted backup |
| Document conversion | Internal authenticated Docling service; no public hostname is part of the application path |

The public proxy is ingress and SSH transport only. Do not build, install or run
application services there. Vercel project `web` is a rollback artifact, not the
current production frontend. Render/Supabase are dev/demo or explicitly chosen
rollback contours and do not prove KZ production state.

## Required release boundary

1. Bind owner approval to one exact SHA, previous SHA/image, service set,
   migration mode, rollback and smoke/cleanup scope.
2. Run the deterministic release evidence gate and independently verify its
   references.
3. Push only through the canonical Kamilya GitHub credential path in
   [`AGENTS.md`](AGENTS.md), then read back the remote SHA.
4. Require successful GitHub CI and immutable artifacts for that same SHA.
5. For backend/API/worker deployment follow
   [`.codex/skills/kamilya-production-deploy/SKILL.md`](.codex/skills/kamilya-production-deploy/SKILL.md).
6. For frontend deployment follow
   [`docs/runbooks/ct137-native-frontend-deploy.md`](docs/runbooks/ct137-native-frontend-deploy.md).
7. Independently verify public/private health, all API/worker image identities,
   CT137 `/healthz`, the changed user journey and disposable cleanup.

Dirty working-tree files are never release input. Build backend and frontend
artifacts from the exact Git object. Do not use blind `git pull`, interactive
guest console, local Docker PostgreSQL or a provider dashboard as a substitute
for the documented release path.

## Migration and data rules

- Default mode is `no-migration`. CT125 may change only under an exact approved
  migration node with fresh backup/restore and rollback evidence.
- Runtime DB access uses the restricted `lms_app` role and tenant/RLS context.
- PostgreSQL, Valkey and internal file/document services are not published to
  the Internet.
- Never place secrets in commands, Git, release archives, logs or documentation.

## Frontend release

GitHub workflow `build-native-frontend.yml` builds the exact accepted SHA for
Linux x64/musl with `NEXT_PUBLIC_API_URL=https://api.kml.kz/api`. The workstation
stages the digest-bound archive and manifest through
`scripts/ops/ct137_native_deploy.py`; the restricted CT137 helper validates
capacity, preserves the current rollback release and atomically switches the
native service. A Proxmox login is not part of routine deployment.

Acceptance requires `https://app.kml.kz/healthz` to return the full target SHA
and a browser check of the changed authenticated flow. A marker or HTTP 200 alone
is insufficient.

## Backend release

The protected KZ release path deploys one immutable image to VM126 and recreates
only the approved API and three worker services. All four containers must report
the same full release SHA and image digest. Private health precedes public health;
failure, mixed identity or timeout triggers the reviewed rollback path.

For no-migration releases CT125 remains unchanged, but current revision and
backup/rollback readiness are still read back according to the selected release
profile.

## Rollback

- Frontend: use the previous verified CT137 release retained by the native
  helper; Vercel remains a separate emergency rollback option only when
  explicitly selected.
- Backend: redeploy the recorded previous immutable image/source using the same
  protected controller and verify API/worker identity again.
- Database: prefer an additive forward fix. Do not downgrade a migration unless
  its downgrade path was explicitly approved and tested.
