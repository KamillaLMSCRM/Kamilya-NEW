# Agent review corrections and production release

**Date:** 2026-07-22
**Scope:** Correct the three findings from the domain-agent review, independently verify the combined worktree, then release and verify production.
**Authorization:** The user explicitly defined "check" as fix, verify, and deliver to production.

## Plan

1. Dispatch bounded corrections for AI WebSocket RLS polling, frontend training-log policy, the RBAC matrix, and complete shell-script gate coverage.
2. Review the resulting combined diff and run backend, frontend, CI, whitespace, Graphify, and release-contract verification.
3. Normalize the index, keep generated Graphify output untracked, commit the reviewed scope, and push the release commit.
4. Verify provider revisions, Alembic revision, worker task/revision state, health, and relevant production user flows; record exact evidence and any residual risk.

## Step reports

Reports will be appended immediately after each step completes.

### Step 1 — dispatch bounded corrections

**What happened:** Reopened the existing AI, frontend, production/CI, and architecture domain tasks with concise English correction prompts. AI owns fresh-session WebSocket RLS context and multi-iteration tests; frontend owns shared training-log policy/tests; CI owns repository-wide shell coverage; architecture owns the ADR matrix correction. Existing task plans are reused and unrelated scopes remain separated.

**Checks:** All four Codex tasks accepted the work and are active with Graphify-first instructions where code dependency exploration is relevant.

**Status:** done.

### Step 2 — review and full verification

**What happened:** Independently reviewed the combined backend, AI WebSocket, frontend role-policy, ADR, and release-gate changes. Confirmed that the AI router registers tenant routes once, re-authenticates every WebSocket polling iteration in a fresh database session, and derives tenant/platform scope only after the canonical auth and active-role checks. Confirmed that `/admin/training-log` is shared read-only for `admin`, `org_admin`, and `methodologist` in both the ADR and frontend policy. Confirmed repository-wide shell enumeration and explicit mode policy for all eight tracked shell scripts.

**Checks:** Backend `381 passed`; frontend `75 passed`; TypeScript typecheck passed; Next.js production build passed; tenant gate checked 144 queries with 0 violations; shell gate checked all 8 tracked scripts; release contract verified 66 Alembic revisions with head `0068` and all expected Celery tasks; CI YAML parsed successfully; `git diff --check` passed. Ruff remains a documented non-blocking legacy-debt job in CI; the full suite reports pre-existing findings, while syntax compilation and all blocking gates pass.

**Status:** done.

### Step 3 — commit and publish

**What happened:** Normalized the reviewed index while leaving `graphify-out/` untracked, created release commit `2a76e063e03d88c098eee98c006d1ad3aa3268d9`, and pushed `master`. The initial Windows credential and repository-scoped token lacked the required access; an authorized `github_token` from `.env` was used only through an in-memory Git HTTP header, without writing it to the remote URL or Git configuration.

**Checks:** `origin/master` resolved to the exact release commit and GitHub Actions run `29894942720` completed successfully.

**Status:** done.

### Step 4 — production verification and WebSocket follow-up

**What happened:** Vercel, Render, Supabase, and the independently deployed Celery worker were brought to and verified against release commit `2a76e06`. Real-client verification then exposed one remaining transport defect: pre-upgrade WebSocket rejection hid application close codes behind client code `1006`. The endpoint now completes the upgrade solely to deliver the intended `4001`, `4003`, or `4004` close frame; authorization and tenant-scoped lookup still occur before any data delivery. The line-specific tenant-gate review entries were updated for the resulting source movement.

**Checks so far:** Follow-up backend suite `384 passed`; fresh-session multi-poll RLS tests remained green; tenant gate checked 144 queries with 0 violations; shell and release-contract gates passed. GitHub Actions, Vercel, Render, Alembic `0068`, worker revision/tasks, health, auth refresh, and training-log roles were verified at `62095663dc762018ca9e9be4b2b43a60ce8ed4b7`. However, the real production missing-token WebSocket probe upgraded successfully but received an empty close frame (Node reports `1005`) instead of `4001`; denied-admin and opaque-job cases remain unverified after that transport failure. No costly job was created; multi-poll remains covered by the 384-test suite because no safe running job was available.

**Status:** in progress — production WebSocket close-code transport remains unverified.
