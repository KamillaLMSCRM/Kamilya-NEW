# ADR-0012: RBAC — Admin vs Methodologist

- **Status:** Accepted
- **Date:** 2026-06-30
- **Context:** B2 UI scoping + audit consistency
- **Supersedes:** nothing — codifies implicit separation that was
  already scattered across `require_role(...)` calls

## Amendment 2026-07-01

Direct learner-course assignment is **methodologist-owned**, not
tenant-admin-owned. The legacy URL `/admin/enrollments` must redirect to the
learning-content surface `/assignments`. API guards for bulk assignment,
assignment listing/removal, and enrollment CSV export should allow
`methodologist` and reject tenant `admin`/`org_admin` by default.
Tenant admins manage organization settings, team/system users, integrations,
and infrastructure; they do not decide individual learning trajectories.

## Amendment 2026-07-21: one account, multiple roles

A tenant user may hold more than one assigned role. `users.role` remains the
primary role used at a new login; `user_roles` is the authoritative set of
roles assigned to that account.

- Adding a role to an existing email does not create another user, change the
  password/profile, or consume another system-user plan slot.
- The user selects one active working mode in the top bar. The backend issues
  new access and refresh tokens with that active role.
- Every request validates the selected role against `user_roles`; a role value
  supplied only by the client or a stale token cannot grant access.
- `require_role(...)` evaluates the active role, not the union of all assigned
  roles. Admin and methodologist interfaces therefore remain separated even
  when the same person performs both jobs.
- A refresh preserves the selected mode. A new login starts in the primary
  role. Migration `0067` backfills missing primary-role assignments.

## Problem

The codebase has two privileged tenant-side roles — `admin` (and
`org_admin`) and `methodologist` — but their
responsibilities are implicit. The closest thing to a spec is the
role list in `app/core/auth.py:20`:

```
ROLES = ['superadmin', 'admin', 'org_admin', 'methodologist', 'student']
```

But that says nothing about who-does-what. Consequences:

1. **UI placement is wrong.** `methodologist` ends up navigating
   `/admin/users` (a page the codebase reserves for system users)
   or `admin/staff/import` (a page reserved for bulk staff ops)
   without any role gate. The user lands, sees controls they
   shouldn't have, gets confused or makes unauthorized edits.

2. **API guards are inconsistent.** `staff_import_router.py:249`
   uses `require_role("admin", "org_admin", "superadmin",
   "methodologist")`. `departments/router.py:118` uses
   `require_role("admin", "methodologist", "superadmin")`. Some
   endpoints that should be methodologist-only (`POST
   /positions/{id}/courses`) end up admin-allowed because the
   original author copy-pasted the looser guard.

3. **No canonical place where "what belongs to whom" is written.**
   Future contributor has to grep `require_role(...)` to infer
   the model, and there's no test that catches a regression.

## Terminology

| Term                | In this codebase                                              |
|---------------------|---------------------------------------------------------------|
| **System user**     | Anyone who logs in to manage the LMS: `admin`, `org_admin`, `methodologist`, `superadmin`. Carries an `access_token`. Distinct from "обучающиеся" below. |
| **Обучающийся**     | End user of LMS content — `student` role. They view courses, take quizzes, earn certificates. Never manage anything. |
| **Tenant admin**    | `admin` / `org_admin` — owns the *tenant infrastructure*: tenant settings, billing, integrations, system user list, superadmin hand-off. |
| **Methodologist**   | `methodologist` — owns the *learning content and staff configuration*: courses, JDs, position/department bindings, quiz authoring, onboarding quiz reset, staff import (Excel/CSV), course review workflow. |
| **Superadmin**      | `superadmin` — platform-level: tenants CRUD, provider keys, impersonation. `tenant_id IS NULL` for these rows. |

The product has one learning-content role: `methodologist`. Migration `0066`
converts the former technical role name and removes it from database
constraints and authorization allow-lists. A separate instructor role may be
introduced later only if it receives its own policy and UX.

## Decision

### 1. Two ownership domains, side by side

```
┌────────────────────────────────────────────────────────────────────┐
│ Tenant (org_admin / admin) — "владелец платформы в компании"       │
│ • tenant settings, branding, default language                      │
│ • integrations (Telegram, WhatsApp, SMTP)                          │
│ • LLM provider keys for the tenant                                 │
│ • system user list (admin / methodologist invite / off)  │
│ • billing, plan upgrades, superadmin hand-off                      │
│ • kiosk admin (link CRUD)                                          │
│ • audit log access                                                  │
│ • AI provider keys (per-tenant)                                    │
└────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────┐
│ Methodologist — "методолог обучения"                                   │
│ • курсы: create / draft / publish / archive                         │
│ • content review (AI-дрaфт → черновик → публикация)                │
│ • quizzes, certificates                                              │
│ • позиции / отделы: CRUD                                            │
│ • правила привязки «должность ↔ курс», «отдел ↔ курс» (B1c)        │
│ • штатное расписание: импорт Excel/CSV, превью, commit (Stage 1d)  │
│ • apply-rules (БД-материализация из rules → enrollments)            │
│ • онбординг-квиз сброс попыток (для своего отдела)                  │
└────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────┐
│ Superadmin — "платформа" (tenant_id IS NULL)                        │
│ • tenants: CRUD + impersonation                                     │
│ • global LLM provider keys                                          │
│ • всё, что в обычном тенанте есть у admin, только поверх всех       │
└────────────────────────────────────────────────────────────────────┘
Обучающийся (student) — потребитель контента. НИЧЕГО не настраивает.
```

Студенты никогда не администрируют. Methodologist никогда не редактирует
tenant-инфраструктуру. Admin никогда не редактирует курсы и правила.

### 2. URL namespace reflects domain

| URL prefix                | Owner               | Pages                                                  |
|---------------------------|---------------------|--------------------------------------------------------|
| `/admin/users` (legacy)   | admin               | list of admin/methodologist accounts           |
| `/admin/team` (ADR-0011)  | admin               | same, renamed                                          |
| `/admin/staff`            | methodologist       | Импорт (Stage 1d) + Структура + Правила (B2)            |
| `/assignments`            | methodologist         | direct learner-course assignment (`manual` enrollments) |
| `/admin/enrollments`      | legacy redirect       | redirects to `/assignments`; not an admin-owned surface |
| `/admin/kiosks`           | admin               | kiosk link CRUD                                        |
| `/admin/integrations`     | admin               | Telegram / WhatsApp / SMTP                             |
| `/admin/providers`        | superadmin (only)   | global LLM provider keys                               |
| `/admin/tenant-providers` | admin               | per-tenant LLM provider keys                            |
| `/admin/super/*`          | superadmin (only)   | tenant CRUD, impersonation                             |
| `/admin/settings`         | admin               | tenant settings, branding                               |
| `/admin/quizzes`          | methodologist       | quiz authoring                                          |
| `/admin/quizzes/assign`   | methodologist       | bulk quiz assignments                                   |

Methodologist can **view** admin pages (read-only) but cannot mutate.
This is enforced via `require_role(...)` per-endpoint, not via page-level
gating (the menu still shows their entries, grayed out where they have
no access).

### 3. Endpoint guards — table

| Endpoint                                                  | Allowed roles                              | Source                                          |
|-----------------------------------------------------------|--------------------------------------------|-------------------------------------------------|
| `GET /v1/users` (`/team`)                                 | `admin`, `org_admin`, `superadmin`         | `users/router.py`                                |
| `GET /v1/users?include_students=true`                     | `admin` only (NOT methodologist)           | same                                            |
| `POST /v1/team/invitations`                               | `admin`, `org_admin`, `superadmin`         | same                                            |
| `POST /v1/admin/staff/import/preview`                     | `admin`, `org_admin`, `superadmin`         | `staff_import_router.py` — **must add guard**   |
| `POST /v1/admin/staff/import/commit`                      | `admin`, `org_admin`, `superadmin`, `methodologist` | existing — both allowed by design (HR import is admin; methodologist on-call can re-run when admin not available) |
| `GET  /v1/admin/staff/apply-rules/status/{task_id}`      | `admin`, `org_admin`, `superadmin`, `methodologist` | existing — both allowed (poll is read-only) |
| `GET /v1/admin/staff/structure`                           | `admin`, `org_admin`, `superadmin`, `methodologist` | existing |
| `POST /v1/positions/{id}/courses`                         | `methodologist`, `admin`, `superadmin`      | `positions/router.py`                            |
| `DELETE /v1/positions/{id}/courses/{cid}`                 | `methodologist`, `admin`, `superadmin`     | same                                            |
| `POST /v1/departments/{id}/courses`                       | `methodologist`, `admin`, `superadmin`     | `departments/router.py` (B1c, 2026-06-30)       |
| `DELETE /v1/departments/{id}/courses/{cid}`               | `methodologist`, `admin`, `superadmin`     | same                                            |
| `POST /v1/courses/{id}/enroll` (self-enroll)               | any tenant user                            | `enrollments/router.py`                          |
| `POST /v1/courses/{id}/enrollments` (bulk by manager)     | `methodologist` | revised 2026-07-01 - direct learner-course assignment is content-domain, not tenant-infra (§6) |
| `GET /v1/courses/{id}/enrollments` (list)                 | `methodologist` | content-domain assignment list |
| `DELETE /v1/courses/enrollments/{id}`                     | `methodologist` | only manual enrollments may be removed directly |
| `GET /v1/courses/{id}/enrollment-stats`                   | `admin`, `org_admin`, `superadmin`, `methodologist` | already shared |
| `GET /v1/admin/export/enrollments` (CSV)                  | `methodologist` | assignment export for learning-content handoff |
| `POST /v1/positions/{id}/assign/{user}`                   | `admin`, `superadmin`                      | auto-enrolls, admin action                       |
| `POST /v1/kiosks/*`                                       | `admin`, `org_admin`, `superadmin`         |                                                 |
| `GET /v1/admin/audit-log/*`                               | `admin`, `superadmin`                      | never methodologist                              |
| `GET /v1/admin/super/*`                                   | `superadmin`                               | tenant_id IS NULL                                |

**Rule of thumb for new endpoints:**

- "Read a thing in this domain" → `*, superadmin` (broadest read).
- "Mutate a domain thing" → `methodologist` only (or `admin` only,
  depending on which domain).
- "Bulk-import / replace a list" → domain-specific (admin for
  users; methodologist for staff/courses/positions).

### 4. Frontend menu reflects domain

Sidebar (`apps/web/src/components/layout/Sidebar.tsx` — or
equivalent):

- **Admin section:**
  - 👥 Команда (`/admin/team`)
  - 🏢 Структура → `/admin/staff?tab=structure`
  - 🎓 Kiosks (`/admin/kiosks`)
  - 🔗 Интеграции (`/admin/integrations`)
  - ⚙️ Настройки (`/admin/settings`)

- **Methodologist section (new, B2+):**
  - 📥 Импорт → `/admin/staff?tab=import`
  - 📐 Правила → `/admin/staff?tab=rules`
  - 📚 Курсы, 🧪 Квизы, 📊 Аналитика → existing positions/courses routes

Sections are independent — admin doesn't see methodologist-only items
and vice versa. **Or:** one combined section with role-gated
visibility. Either is fine; the key is **methodologist does not see
"Команда" or "Kiosks" as actionable items** because they're admin-only.

For B2a (this epic), we choose: **one combined Admin section**,
with role guards inline. Future epic (B3) can split sections.

### 5. Where the rules live

The single source of truth is:

- **API:** `require_role(...)` decorator at endpoint declaration.
  Inline in router files. See table in §3.
- **Frontend:** `useAuthStore` exposes `user.role` and
  `<AuthGuard roles={["methodologist"]}>` (when introduced) or
  per-component `if (user.role === 'methodologist')` checks.
- **No DRY registry yet.** v1.1 epic can introduce
  `app/core/rbac.py::ROLE_GROUPS` exposing
  `ROLE_GROUPS.learning_content = {"methodologist","admin","superadmin"}`
  shared across both sides via OpenAPI codegen. Out of scope for B2.

### 6. Test coverage

Add a cross-cutting test:

```python
# tests/test_rbac_methodologist_admin_separation.py

# Methodologist CAN:
# - POST /v1/positions/{id}/courses
# - DELETE /v1/positions/{id}/courses/{cid}
# - POST /v1/departments/{id}/courses
# - DELETE /v1/departments/{id}/courses/{cid}
# - GET /v1/positions, GET /v1/courses

# Tenant admin CANNOT:
# - GET /v1/users (without ?include_students=true; that flag rejects them)
# - POST /v1/team/invitations
# - POST /v1/courses/{id}/enrollments (allowed for methodologist; denied for tenant admin)
# - POST /v1/kiosks/*
# - GET /v1/admin/super/*
```

## 6. Revision 2026-07-01 - assignments moved out of admin

**Decision:** direct learner-course assignment is methodologist-owned
only. Tenant `admin` / `org_admin` do not own individual learning
trajectories.

Current behavior:

- Frontend surface is `/assignments`.
- Legacy `/admin/enrollments` redirects to `/assignments`.
- Sidebar and CommandPalette show assignments only to `methodologist`.
- Backend guards for bulk assignment/list/delete/export allow `methodologist`.
- Manual assignment picker fetches active `student` rows only.
- Backend rejects manual enrollment for non-student users.
- Direct delete is allowed only for `source='manual'`; rule-driven rows must be removed by changing department/position rules.

**Why:** the `TZ_COURSE_ASSIGNMENT_ACCESS_v1.md` model treats Level 4
manual overrides as learning-content work. Admins manage tenant
infrastructure and system users; methodologists manage course assignment
logic and exceptional learner assignments.

**Not changed:** admin still owns tenant infrastructure
(`/admin/team`, `/admin/kiosks`, `/admin/settings`, `/admin/integrations`,
`/admin/audit-log`, `/admin/super/*`).

## Consequences

### Positive

- Clear answer to "who edits what" for every new contributor.
- B2 UI can be implemented as the **methodologist-only** `/admin/staff?tab=rules` page without ambiguity about which role owns it.
- Future ambiguity (e.g., "can methodologist edit SSO config?") resolves in seconds by looking at this ADR §3.

### Negative / cost

- Existing endpoints with `require_role("admin", "methodologist", "superadmin")` may not match the §3 table. They'll be fixed as part of B1c/B2a audits. **Estimated 5–10 endpoints to align.**
- Frontend `/admin/users` currently has no role gate — methodologist sees "Команда" entry and gets an empty list (server-side filter excludes students). Visible UX gap; fix in B2.
- `staff_import_router.py::import_preview` should be admin-only (file uploads, dangerous to leak org structure). Currently allow-list lets methodologist in. To audit.

## Cross-references

- ADR-0003 (multi-tenancy): RBAC operates inside a tenant boundary.
- ADR-0008 (auth strategy): role comes from JWT claim + DB refresh.
- ADR-0009 (storage backend): not RBAC-related but the docs use the same vocabulary.
- ADR-0011 (users/staff refactor): the architectural foundation that this ADR formalizes further.
- Migration: `0035_departments.py` (Department table) — keeps PositionCourse authoritative regardless of role.
- `app/core/auth.py:20` (ROLES list) — needs `'methodologist'` (already fixed 2026-06-30) and documented here.
- Tests: new file in `apps/api/tests/test_rbac_admin_methodologist_separation.py`.

## Action items (this epic)

1. ✅ Add `'methodologist'` to `ROLES` — already done in commit prior to this ADR.
2. ✅ Audit every `require_role(...)` call against §3. Fix deviations.
3. ✅ Add `tests/test_rbac_admin_methodologist_separation.py`.
4. 🔲 Add `useAuthGuard` (or per-component checks) in frontend for pages.
5. ✅ B2a: third tab "📐 Правила" in `/admin/staff` — visible to methodologist and admin (both are owners of this domain). Forbids students.
6. 🔲 Document the role split in `DESIGN.md` and `TZ.md` if they mention staff (admin only). Update to specify the split.

## Action items (revision 2026-07-01, §6)

1. ✅ Move the UI implementation to `/assignments`.
2. ✅ Redirect legacy `/admin/enrollments` to `/assignments`.
3. ✅ Restrict assignment navigation to `methodologist`.
4. ✅ Restrict backend assignment/list/delete/export guards to `methodologist`.
5. ✅ Reject non-student manual enrollments.
6. ✅ Reject direct deletion of rule-driven enrollments.
7. ✅ Add focused regression coverage in `tests/test_enroll_users_validation.py` and `tests/test_enrollments_rbac.py`.
