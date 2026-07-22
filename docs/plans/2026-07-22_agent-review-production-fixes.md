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
