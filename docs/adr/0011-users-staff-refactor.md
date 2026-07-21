# ADR-0011: Users / Staff / Positions refactor

- **Status:** Accepted
- **Date:** 2026-06-28
- **Context:** audit followup + UX review (2026-06-28)

## Problem

Three intertwined UX issues in the Personnel/Admin section:

1. **`/admin/users` mixes students with staff.** Methodologist sees a
   table dominated by `role=student` rows that they cannot edit
   meaningfully (students are auto-provisioned via Telegram-bot or
   kiosk). The "Add student" modal is wrong: students are not
   managed by humans.

2. **Personnel workflow is split across four pages.**
   `/admin/staff` (Excel/CSV import), `/admin/employees` (tree view),
   `/positions` (job descriptions), `/admin/enrollments` (direct
   course assignment). The first three form a single workflow
   (import → tree review → configure JD); the fourth is an admin-only
   escape hatch.

3. **`Department` is a free-text string inside `Position.department`.**
   This means:
     - "HR", "hr", "Hr" become three separate departments in the
       tree (no canonicalization).
     - No way to attach shared metadata to a department (head,
       budget, headcount target).
     - Typos compound over time.

## Decision

### 1. `users` API: only non-student CRUD

`/v1/users` is renamed `/v1/team` and serves **only** the
team-management surface: methodologist, admin, org_admin, superadmin.

- `GET /v1/team` filters `role NOT IN ('student',)` by default. New
  `?include_students=true` opt-in for admin (rarely used; we keep
  `/v1/admin/students` as a separate read-only list).
- `POST /v1/team` accepts `role` only from `{methodologist, admin,
  org_admin}`. The `superadmin` role is platform-level and cannot
  be assigned from a tenant context.
- Bulk-invite (`POST /v1/team/invitations/bulk`) only sends to
  non-student roles; student invitation is the Telegram-bot flow.

Backward compatibility: `/v1/users` keeps working for the duration
of v1.0 GA; it returns the same payload as `/v1/team` plus
optional students. We'll remove the alias in v1.1 once all
frontend routes migrate.

### 2. `staff_tree` endpoint moves under `/admin/staff`

The single endpoint `GET /admin/staff/tree` (from
`apps/api/app/modules/users/staff_tree_router.py`) is moved to the
**positions** module's admin namespace. The frontend `/admin/staff`
page combines the existing import wizard with a new "Structure"
tab that calls this endpoint.

URLs:
  - Old: `GET /admin/staff/tree`
  - New: `GET /admin/staff/structure`
  - The old URL keeps working for one minor version.

### 3. `Department` becomes a real table

Migration 0035 creates:

```sql
CREATE TABLE departments (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,                 -- "Human Resources" (display)
  slug TEXT NOT NULL,                 -- "hr" (normalized, lowercase)
  parent_id UUID REFERENCES departments(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, slug)
);

CREATE INDEX idx_departments_tenant ON departments(tenant_id);
```

`Position` gets a new FK column:

```sql
ALTER TABLE positions ADD COLUMN department_id UUID
  REFERENCES departments(id) ON DELETE SET NULL;
```

For v1.0 we keep `Position.department` (text) populated in parallel
for backward compat; a backfill migration creates one Department per
unique `(tenant_id, lower(department))` triple, then sets
`Position.department_id` accordingly. Future migration 0036 will
drop the text column.

### 4. Frontend sidebar restructured

```
👥 Сотрудники (renamed from "Персонал")
├── Импорт + Структура  ← /admin/staff (tabs: Import | Structure)
├── Должности           ← /positions
└── Команда             ← /admin/team (former /admin/users, non-students only)

⚙️ Админ (unchanged)
```

`/admin/students` (read-only list with progress, optional) becomes
accessible from the "Команда" page via a small toggle button —
not in sidebar because it duplicates the tree view.

## Consequences

### Positive

- Methodologist no longer sees student rows in their working
  list. The "Add user" modal stops being misleading.
- Department canonicalization fixes the "HR/hr/Hr" duplication
  bug that already bit us during 1XLSX imports.
- Combining `/admin/staff` and `/admin/employees` into one
  page reduces cognitive load — methodologists see import →
  review → configure JD as one flow.
- Clear ownership: HR manager uses Сотрудники, content author uses
  Контент. Less overlap.

### Negative / costs

- Migration 0035 is data-touching: must backfill `departments` from
  `Position.department`. Downtime risk is low (additive table +
  nullable FK), but the backfill script must be tested on a copy
  of prod data before the cutover.
- `/v1/users` is a public API used by internal code. Keeping the
  alias adds a maintenance burden (two URLs to keep in sync) until
  v1.1 removes it.
- The "Combine import + structure tabs" pattern introduces tab
  state in the frontend; we accept the additional UX complexity.

## Alternatives considered

- **Drop `/admin/team` entirely, rely on `/admin/staff` tree.**
  Rejected — CRUD for methodologist/admin org-level is still needed
  (invite, deactivate, change role). Tree is read-only.
- **Make `Position.department` a true FK now, not later.**
  Rejected for v1.0 — the backfill is risky and we already have
  customers on the string column. Defer to v1.1.
- **Keep `/admin/users` and just hide students in the UI.**
  Rejected — backend should never serve data the UI can't
  safely render. Server-side filter is the contract.

## Cross-references

- Migration: `apps/api/alembic/versions/0035_departments.py`
- Backend: `apps/api/app/modules/users/router.py` (rename to team_router.py deferred)
- Frontend: `apps/web/src/app/admin/users/page.tsx` → `team/page.tsx`
- Related: ADR-0003 (multi-tenant), audit §1 (Phase 1 inventory)