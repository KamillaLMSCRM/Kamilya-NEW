# RBAC and auth documentation canon

**Date:** 2026-07-21
**Scope:** Documentation only — `docs/` and `PROJECT*.md`. No runtime, migration, database, production, or deployment changes.

## Step 1 — Establish the documented and runtime baseline

**Intent:** Re-read the accepted RBAC/auth ADRs and the confirmed role/auth runtime contracts; record the scope and contradictions to resolve.

**What I found:** `teacher` is absent from runtime role constants and current role models. The active tenant role is selected through `POST /v1/auth/switch-role`, encoded in access/refresh tokens, and used by `require_role(...)`. The main tenant layout blocks `admin`/`org_admin` from learning surfaces, and the principal content routers allow `methodologist` (plus `superadmin`). ADR-0012 still contains earlier shared-role endpoint tables and UI wording that conflict with this current policy. ADR-0008 still states `SameSite=Strict` and Telegram without refresh, while the current router sets `Secure; HttpOnly; SameSite=None; Partitioned` and issues a refresh cookie after verified Telegram code login.

**Checks:** Read `apps/api/app/core/auth.py`, `apps/api/app/modules/auth/{router,service}.py`, selected role-guarded routers, and `apps/web/src/components/layout/{Layout,Sidebar,TopBar}.tsx` without modifying runtime code.

**Status:** done

## Step 2 — Consolidate ADR-0012

**Intent:** Separate historical context from the current policy, make the strict admin/methodologist ownership split unambiguous, and remove obsolete role tables/checklists without restoring `teacher`.

**Files:** `docs/adr/0012-rbac-admin-vs-methodologist.md`

**Checks:** Read against `apps/api/app/core/auth.py`, auth role-switching code, frontend layout/navigation, and role guards.

**What I changed:** Replaced the transitional endpoint inventory with one current-policy record. It now defines the strict ownership boundary, the active-role contract, the compact UI/API/redirect matrix, legacy redirects, and backend/frontend acceptance criteria. Historical shared mutation guards are explicitly conformance debt rather than policy exceptions; `teacher` remains excluded.

**Checks:** Re-read against the current role constants, role switch endpoint, main layout redirects, sidebar visibility, and representative content/admin guards.

**Status:** done

## Step 3 — Align ADR-0008 with the confirmed auth runtime

**Intent:** Document current cookie attributes, refresh behavior, and active-role validation based only on the runtime implementation.

**Files:** `docs/adr/0008-auth-strategy.md`

**Checks:** Read against `apps/api/app/modules/auth/router.py`, `service.py`, and `app/core/auth.py`.

**What I changed:** Replaced the outdated SameSite=Strict and access-only Telegram descriptions with the observed cross-site cookie contract and current refresh behavior. Documented active-role issuance/refresh, the stateless refresh limitation, and the current primary-role validation conformance gap without changing runtime.

**Checks:** Read the cookie helpers, Telegram code-login response, refresh service, role-switch endpoint, and active-role resolver in the current auth runtime.

**Status:** done

## Step 4 — Add the canonical role matrix and test acceptance criteria

**Intent:** Put compact UI/API/redirect ownership and backend/frontend role-matrix acceptance criteria next to the RBAC canon.

**Files:** `docs/adr/0012-rbac-admin-vs-methodologist.md`

**Checks:** Cross-check every matrix row with runtime route guards and frontend role routing.

**What I changed:** Added the UI-surface, API-capability, and redirect-target role matrix plus explicit backend/frontend acceptance criteria to ADR-0012.

**Checks:** Matrix rows were checked against the active-role switch target, main layout redirects, sidebar visibility, and representative API guards.

**Status:** done

## Step 5 — Audit references and finish verification

**Intent:** Search the permitted documentation for contradictory role/auth wording, validate Markdown links and the diff, and leave the worktree uncommitted.

**What I found:** Current canonical documents contain no stale policy statement.
The only `teacher` and `SameSite=Strict` matches are intentional historical or
prohibitive wording in ADR-0012, ADR-0008, and the existing handoff. Dated
audits, handoffs, and plans outside the current source-of-truth set retain
historical wording and were deliberately not rewritten.

**Checks:** Scoped `rg`, Markdown link-target checks, and `git diff --check`
for this task's files passed. The shared worktree contains unrelated concurrent
changes; they were not modified. No commit or push was made.

**Status:** done

## Correction — Shared training-log matrix row

**Date:** 2026-07-22

**What I changed:** Added `/admin/training-log` to the `admin`/`org_admin` UI
surfaces and made its read-only reporting capability explicit. The route remains
shared with `methodologist`; it grants no learning-content, learner-assignment,
or workforce-learning mutation capability to tenant admins.

**Cross-check:** The visible frontend role-policy change currently lists
`/admin/training-log` among admin-blocked routes. It does not yet match this
canonical ADR decision. No frontend file was edited; the frontend owner needs
to reconcile that policy separately.

**Status:** done
