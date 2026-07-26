# Methodologist information architecture remediation

Date: 2026-07-26
Owner: Codex
Status: WP1-WP2 released; WP3 pending

## Goal

Make the methodologist cabinet follow real user jobs instead of exposing
historical implementation boundaries. Remove duplicated editing surfaces,
establish one source of truth for every training decision, and keep tenant
administration separate from learning management.

## Current staff-page diagnosis

| Current surface | Actual behavior | Overlap | Decision |
|---|---|---|---|
| `Импорт` | Excel/CSV preview, column mapping, commit and rule recomputation | No functional duplicate | Keep under `Сотрудники и структура` |
| `Структура` | Department -> position -> employee tree plus course completion percentages | The hierarchy is unique; learning results repeat `Журнал обучения` | Keep the hierarchy; remove result ownership and link to the training log |
| `Добавить сотрудника` | Creates a learner with department and position and applies inherited rules | No duplicate | Keep under `Сотрудники и структура` |
| `Привязка курсов` / department | Mutates persistent `department_courses` rules and materializes enrollments | Valid function, but misplaced in the staff-import screen | Move to `Правила обучения` |
| `Привязка курсов` / position | Shows positions and sends the user to the position qualification card | Duplicates the `Должности` entry point | Remove this duplicate editor/list from Staff; keep the position card canonical |
| `Курсы компании` | Copies a course binding to every department that exists at the time | Pretends to be an organization rule but does not cover departments created later | Replace with a persistent organization-level rule |

### UX/UI defects confirmed in the current implementation

- The visible tabs are local React state. Clicking a tab does not update the
  query string, so refresh, Back/Forward and copied links do not preserve the
  current context.
- Product navigation uses emoji as icons. Replace them with the project's
  Lucide icon set and mark decorative icons `aria-hidden`.
- `Штатное расписание` describes an HR document, while the screen manages
  employees and the organizational hierarchy. The product name must be
  `Сотрудники и структура`.
- The default tab is `Импорт`, although file import is an occasional setup
  action. The daily working view must open on `Структура`.
- The structure tree mixes organizational facts with course-completion
  percentages. This makes it a second, incomplete training-results dashboard
  and obscures the hierarchy.
- The frontend grants Staff and rule-editing capabilities to tenant `admin`
  and unscoped `superadmin`, contradicting ADR-0012 and the target
  governance-only tenant-admin role.
- Loading copy uses three periods rather than the ellipsis character, and
  long department, position and course names need explicit truncation plus a
  discoverable full value.
- The import contract accepts `phone`, but the current `User` model has no
  employee-phone field. Until the field is persisted, the UI must not claim
  that phone data was saved; the durable fix is an additive user-profile
  migration and explicit export/privacy handling.

## Sources of truth

| Decision or data | Canonical owner |
|---|---|
| Employee identity, department and position | `Сотрудники и структура` |
| Position job instruction and qualification profile | `Должности` |
| Competency catalog | `Матрица компетенций`; position cards consume it |
| Mandatory course for the entire tenant | organization training rule |
| Mandatory course for a department | department training rule |
| Mandatory course for a position | position qualification card |
| One-off learner-course exception | `Назначения на курс`, source `manual` |
| Reusable audience | `Группы обучения` |
| Ordered multi-course curriculum | `Программы обучения` |
| Completion, scores, certificates and evidence | `Журнал обучения` |

Rule precedence for an employee:

1. position rule;
2. department rule;
3. organization rule.

Duplicate course grants collapse into one enrollment. Manual, cohort and
learning-program grants remain protected from automatic rule removal.
Completed learning is never deleted when a rule is removed.

## Target methodologist navigation

### Overview

- Dashboard
- Training log

### Content

- Documents
- AI generation
- Courses
- Tests
- Learning programs

### People and delivery

- Employees and structure
- Invitations
- Learning groups
- Training rules
- Course assignments

### Qualifications

- Positions
- Competency catalog

## Work packages

### WP0 - independent audit and contract confirmation

**Agent:** inexpensive read-only reviewer (`gpt-5.6-luna`, medium).
**Write scope:** none.

Checks:

- every Staff tab, endpoint and mutated table;
- overlap with positions, competencies, cohorts, assignments, programs and
  training log;
- role drift between frontend, API and ADR-0012;
- organization-course fan-out failure for new departments.

Gate: no implementation starts until the source-of-truth table above is
confirmed or amended by the orchestrator.

### WP1 - persistent organization training rules

**Agent:** balanced low-cost backend worker (`gpt-5.6-terra`, medium).
**Write scope:**

- `apps/api/app/modules/training_rules/**`;
- additive Alembic migration after revision `0075`;
- narrowly required changes in
  `apps/api/app/modules/positions/assignment_service.py`,
  `apps/api/app/modules/positions/batch_service.py` and model registration;
- backend tests for this package only.

Requirements:

1. Add a tenant-scoped persistent organization-course rule table. Do not
   materialize an organization rule as a snapshot of current departments.
2. Add list/attach/detach endpoints owned by `methodologist`.
3. Extend enrollment recomputation to include organization rules with
   precedence `position > department > organization`.
4. Use enrollment source `organization`; do not remove manual, cohort,
   learning-path or completed enrollments.
5. Apply the rule to newly imported or manually added employees through the
   existing recomputation kernel.
6. Add RLS, indexes, uniqueness and cross-tenant tests following current
   migration patterns.
7. Tighten department-course mutations to methodologist ownership. Platform
   superadmin may operate only through controlled tenant impersonation.
8. Validate every course against the current tenant before writing any
   organization or department binding. An opaque foreign/nonexistent UUID must
   not create a rule row.
9. Keep old batch attach/detach endpoints temporarily as compatibility
   endpoints, but remove them from product UI and mark them deprecated.

Verification:

- focused unit and integration tests;
- migration upgrade on an empty and current test schema;
- explicit duplicate, detach, completed-course and cross-tenant cases.

### WP1B - normalize staff import hierarchy

**Agent:** inexpensive backend worker (`gpt-5.6-luna`, high), independent
write scope and orchestrator review.
**Write scope:**

- `apps/api/app/modules/users/staff_import_service.py`;
- narrowly required staff-import schemas/tests;
- no navigation or assignment-rule UI.

Requirements:

1. Resolve or create a canonical `Department` first.
2. Resolve or create a `Position` by normalized name inside that department
   and set `Position.department_id` immediately.
3. Assign the learner to that canonical position.
4. Preserve preview/commit agreement and idempotency for repeated imports.
5. Treat case/spacing variants as one department/position while preserving a
   stable display name.
6. Cover duplicate rows, repeated import, manual employee creation and
   cross-tenant isolation.

### WP2 - frontend consolidation

**Agent:** inexpensive frontend worker (`gpt-5.6-luna`, high).
**Write scope:**

- `apps/web/src/app/admin/staff/page.tsx`;
- `apps/web/src/app/staff/page.tsx`;
- new `apps/web/src/app/training-rules/**`;
- new or moved components under `apps/web/src/features/training-rules/**`;
- `apps/web/src/lib/routeRegistry.ts`;
- `apps/web/src/i18n/locales/{ru,en,kk}.json`;
- focused frontend tests.

Requirements:

1. Rename `Штатное расписание` to `Сотрудники и структура`.
2. Keep only `Структура` and `Импорт`; default to Structure.
3. Keep manual employee creation on that screen.
4. Remove course-result cards and employee progress ratios from the
   organizational hierarchy. Add a clear link to the Training log.
5. Create `Правила обучения` with:
   - organization courses backed by the new persistent API;
   - department rules backed by existing department endpoints;
   - a read-only position overview linking to the canonical position card.
6. Do not expose the old `Курсы компании` fan-out workflow.
7. Before attach/detach, show a consequence preview: affected employees,
   enrollments to add, in-progress enrollments to remove and protected
   completions. A destructive change requires explicit confirmation.
8. Preserve legacy deep links by redirecting:
   - `?tab=rules` -> `/training-rules?scope=department`;
   - `?tab=company-courses` -> `/training-rules?scope=organization`.
9. Use URL-backed tabs, responsive controls, no emoji as product icons, and
   no text or button clipping at 360, 768 and 1440 px.
10. Show this route only to the active `methodologist` role.

Verification:

- route-registry and component tests;
- TypeScript;
- production build;
- desktop and mobile screenshots.

### WP3 - remaining P1 cabinet consolidation

**Agents:** sequential inexpensive frontend workers (`gpt-5.6-luna`,
medium/high), one bounded write set at a time.

1. Add learner Learning programs to learner navigation.
2. Rename/move tenant-admin `Настройки` to `Мой профиль`; do not present
   `/users/me` as company settings.
3. Merge `Конструктор тестов` and `Назначить тест` into one Tests route with
   URL-backed internal tabs.
4. Make Documents the canonical source library; AI generation selects existing
   sources and does not become a second document-management surface.
5. Reframe cohorts as reusable audiences. New course/program delivery starts
   from the course or program; the cohort does not own a competing course
   catalog.

Each subtask requires its own focused tests and independent orchestrator
review before the next subtask starts.

### WP4 - P2 navigation grouping

1. Group Positions and Competencies under `Qualifications`.
2. Group Training log and future survey analytics under
   `Control and results`.
3. Split kiosk device administration from methodologist-owned learning scope.
4. Rename superadmin home to `Platform` and expose `Tenants` directly.

No P2 item may be implemented merely as a label change while the underlying
route ownership remains inconsistent.

## Agent operating rules

- Agents never push, merge, deploy or read secret values.
- Agents edit only their declared write scope.
- Schema/RBAC work uses the balanced model; bulk UI/copy/tests use the cheaper
  model.
- Coding agents must report changed paths, tests run and unresolved risks.
- The orchestrator reviews every diff, runs broader tests, fixes integration
  defects, commits with `kamilla_lms_crm@proton.me`, pushes non-interactively
  and performs production browser QA.
- Only one write agent runs at a time because WP1 and WP2 have a dependency.

## Release gates

1. No active-role capability union.
2. Tenant admin cannot mutate workforce-learning rules.
3. Organization rules cover employees in departments created after the rule.
4. Existing manual/cohort/program/completed learning is not revoked.
5. Staff UI contains no hidden duplicate rule editor.
6. Frontend tests, backend focused/full tests, TypeScript and production build
   pass.
7. GitHub Actions, Render and Vercel reach the reviewed revision.
8. Production QA covers methodologist desktop/mobile, tenant-admin denial and
   one learner whose effective courses combine all three rule scopes.

## Progress

### Step 1 - current-state diagnosis

**What changed:** the orchestrator and an independent `gpt-5.6-luna`
reviewer traced Staff, Positions, Competencies, Cohorts, Assignments, Learning
programs and Training log. Both found the same ownership split. The reviewer
also confirmed:

- department mutations expose an invalid tenant-admin capability;
- batch attach stores unvalidated course UUIDs;
- organization courses are only a snapshot of current departments;
- staff import creates positions before canonical departments;
- rule removal can revoke in-progress rule-driven enrollments and therefore
  needs a consequence preview.

**Status:** done

### Step 2 - backend organization rules

**Agent:** `Confucius`, `gpt-5.6-terra`, medium; backend-only forked
workspace.

**What changed:**

- revision `0076` adds persistent tenant-scoped organization course rules,
  FORCE RLS, tenant/course/author validation and application-role grants;
- methodologist-only list/attach/detach and read-only impact preview API;
- enrollment recomputation now applies `position > department >
  organization`, protects manual/cohort/program/unknown/completed learning
  and updates stale managed-source precedence;
- organization rules apply only to active learner accounts, not tenant admins
  or methodologists;
- department rule mutations are methodologist-only and reject unpublished,
  missing or foreign-tenant courses.

**Verification:** migration downgrade/upgrade on PostgreSQL; RLS/policy/grant
inspection; 71 focused tests; full backend suite 536 passed with the same
three baseline failures (one pre-existing learning-program trigger test and
two Python 3.12 syntax tests running under local Python 3.11).

**Status:** done

### Step 2B - normalized staff hierarchy

**Agent:** `Harvey`, `gpt-5.6-luna`, high; isolated staff-import/manual-add
write scope.

**What changed:**

- import and manual creation now write canonical
  `Department -> Position(department_id) -> User`;
- whitespace/case variants and repeated personnel-number rows are
  idempotent;
- preview and commit share projected row state;
- existing department lookup covers both display name and technical slug;
- real PostgreSQL coverage confirms repeat-import and tenant isolation.

**Verification:** 20 focused import tests, one additional database-backed
hierarchy test and 53 combined organization-rule/import tests.

**Status:** done

### Step 3 - frontend consolidation

**Agent:** `Lovelace`, `gpt-5.6-luna`, high; isolated frontend write scope.

**What changed:**

- `Сотрудники и структура` now contains only the daily structure view,
  manual employee creation and file import;
- department and company course tabs were removed instead of being kept as
  competing editors;
- `/training-rules` is the canonical methodologist-only workspace for
  organization and department rules;
- position rules are read-only in that workspace and link to the canonical
  position qualification card;
- organization and department changes require a server-calculated consequence
  preview before confirmation;
- legacy Staff query links redirect to the matching rule scope;
- attached archived courses remain readable, but only published courses can be
  added;
- staff import now persists optional phone and hire date fields; later imports
  that omit optional columns preserve the stored values.

**Review corrections by orchestrator:**

- removed the agent's accidental loss of qualification-test coverage and
  replaced obsolete Staff-rule tests with dedicated Training Rules tests;
- added preview loading/error handling and prevented duplicate mutations;
- corrected tenant-admin copy and methodologist-only ownership;
- added mobile page spacing and stable icon/button layout;
- added migration `0077` rather than leaving the import UI with false
  persistence claims.

**Verification:**

- Alembic `0076 -> 0077 -> 0076 -> 0077` on PostgreSQL;
- database inspection confirms nullable `users.phone` and `users.hire_date`;
- 28 focused backend tests;
- 143 frontend tests;
- TypeScript passed;
- production Next.js build passed;
- full backend suite: 544 passed, with the same three baseline failures
  unrelated to this package (one privileged-test trigger expectation and two
  Python 3.12 syntax tests executed under Python 3.11).

**Status:** done

### Step 4 - remaining P1 work

**Status:** pending

### Step 5 - integration and production QA

**What was verified:**

- GitHub Actions completed successfully for the reviewed frontend revision;
- Render deployed the organization-rule API and migrations `0076` and `0077`;
- Vercel production alias `app.kml.kz` served the reviewed frontend revision;
- production health returned `ok`, and unauthenticated organization-rule and
  preview requests returned `401` rather than `404`;
- demo methodologist production QA confirmed:
  - Staff contains only `Structure` and `Import`;
  - the structure shows organization facts and links to Training log, without
    course-completion percentages;
  - Training Rules has organization, department and read-only position scopes;
  - position rows deep-link to the position qualification card;
- production mobile QA at 360 px initially found a CSS Grid overflow
  (`scrollWidth=406`); the reviewed fix changed the base grid track to
  `minmax(0, 1fr)`, after which both body and document `scrollWidth` equal
  `360`.

**Status:** done for WP1-WP2
