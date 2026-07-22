# ADR-0012: RBAC — Admin, Methodologist, and active role

- **Status:** Accepted
- **Date:** 2026-06-30
- **Last consolidated:** 2026-07-21
- **Context:** Tenant ownership boundaries, multi-role UX, and authorization consistency

## Status and historical context

This ADR is the canonical product policy for tenant roles. It supersedes earlier
tables, examples, and action lists in this record that permitted overlapping
admin and learning-content mutations without naming an explicit exception.

Earlier implementation notes described a transitional state in which some staff
and course-rule endpoints accepted both tenant admin and methodologist roles.
Those notes are historical evidence of the migration, not current policy. A
runtime guard that still differs from this ADR is a conformance defect for its
backend owner; it is not an alternative RBAC rule.

The former technical role `teacher` was canonicalized to `methodologist` by
migration `0066`. `teacher` is not a compatibility alias, UI label, token value,
or permitted authorization role. A future instructor role requires a separate
ADR, product workflow, authorization policy, and UX.

## Terminology

| Term | Meaning |
|---|---|
| **System user** | A tenant-side operator: `admin`, `org_admin`, or `methodologist`. System users manage the LMS; they are distinct from learners. |
| **Learner** | A user operating in the `student` role. Learners take assigned training and never manage the tenant or learning configuration. |
| **Tenant admin** | `admin` or `org_admin`, responsible for the tenant workspace and its operational infrastructure. |
| **Methodologist** | `methodologist`, the single learning-content role responsible for learning design, staff-learning configuration, and learner trajectories. |
| **Platform superadmin** | `superadmin`, a platform operator with no ordinary tenant context. Platform operations are performed through dedicated platform routes or impersonation. |
| **Active role** | The one tenant role selected for the current session. It is the role evaluated by API guards and reflected in navigation. |

## Decision

### 1. Ownership boundaries

Tenant administration and learning management are separate domains.

| Domain | Owner | Included responsibilities | Explicitly excluded |
|---|---|---|---|
| Tenant infrastructure | `admin`, `org_admin` | Tenant settings and branding, system-team accounts, kiosk links, integrations, plan/billing-facing controls, operational configuration | Course authoring, documents, quizzes, staff-learning rules, direct learner assignment |
| Learning content and workforce learning configuration | `methodologist` | Documents, AI/manual/SCORM courses, review and publication, lessons, quizzes, positions, departments, staff import and structure, learning rules, cohorts, paths, competencies, surveys, announcements, direct assignments, training results | Tenant settings, integrations, kiosk administration, system-team administration |
| Learning consumption | `student` | Assigned courses, quizzes, certificates, learner-only learning-path and survey views | Any tenant or learning configuration |
| Platform operations | `superadmin` | Tenant lifecycle, global provider keys, platform diagnostics, controlled impersonation | Acting as an unscoped tenant user in the tenant UI |

Read-only operational reporting may be shared only when the surface is named in
the matrix below. Shared reads do not grant either role the other role's write
capabilities.

### 2. One account, several assigned roles

A tenant account may have several assigned tenant roles.

- `users.role` is the primary role used for a new login.
- `user_roles` is the authoritative role-assignment set for the account.
- Adding a role to an existing email must not create a second user, alter the
  profile or password, or consume another system-user plan slot.
- The user selects one active working role. Role switching mints new access and
  refresh tokens for that selected role.
- Authorization evaluates the active role, never the union of assigned roles.
  A person who holds both admin and methodologist roles must switch modes before
  using the other domain.
- The server must reject a selected role that is not assigned to the account;
  a client-provided or stale token value cannot add a capability.
- Refresh preserves the selected active role. A new login starts in the primary
  role.

### 3. Canonical role matrix

The matrix describes product ownership. API authorization remains the security
boundary; sidebar visibility, page guards, and redirects must agree with it.

| Active role | UI surfaces | Key API capabilities | Redirect target / boundary |
|---|---|---|---|
| `admin`, `org_admin` | `/admin`, `/admin/team`, `/admin/kiosks`, `/settings`, `/admin/settings/integrations`, certificate-template settings, `/admin/training-log` | Manage system users and their assigned tenant roles; manage tenant settings, kiosk links, and integrations; read the shared training log only (no learning-content, learner-assignment, or workforce-learning mutations) | Role switch lands on `/admin`. Direct navigation to learning-management routes returns to `/admin`. |
| `methodologist` | `/ai/generate`, `/courses`, `/documents`, `/quizzes`, `/staff`, `/positions`, `/assignments`, `/learning-paths`, `/cohorts`, `/competencies`, `/surveys`, `/announcements`, `/admin/training-log` | Create/review/publish learning content; configure workforce learning; manage rules and direct assignments; access learning results | Role switch lands on `/dashboard`. Legacy `/admin/enrollments` redirects to `/assignments`; `/admin/employees` redirects to staff structure. |
| `student` | `/student`, `/my-courses`, `/my-quizzes`, `/certificates`, learner-specific paths and surveys | Read and complete assigned learning; submit learner responses; retrieve own certificates | Role switch lands on `/student`. Management routes must not be actionable. |
| `superadmin` | `/admin/super/*`, `/admin/providers` | Platform tenant lifecycle, global provider configuration, diagnostics, and controlled impersonation | Platform users are redirected away from tenant surfaces to `/admin/super`; tenant users are redirected away from platform surfaces to their dashboard. |

`/admin/training-log` is an explicit shared read-only reporting surface for
tenant admins and methodologists. It does not make learner assignment or course
configuration an admin capability.

The following legacy locations are not ownership exceptions:

| Legacy location | Required behavior |
|---|---|
| `/admin/users` | Redirect to `/admin/team`. The team surface excludes learners by default. |
| `/admin/enrollments` | Redirect to `/assignments`; manual learner-course assignment is methodologist-owned. |
| `/admin/employees` | Redirect to the staff-structure surface. |
| `/admin/staff` | Retained route compatibility for the methodologist staff surface; the current navigation uses `/staff`. |

### 4. API policy

New endpoints must choose an ownership domain before implementation.

- A tenant-infrastructure mutation is admin-only (`admin`/`org_admin`), with
  platform-only exceptions handled through dedicated `superadmin` routes.
- A learning-content or workforce-learning mutation is methodologist-only.
- Learner mutations are restricted to the learner's own assigned learning.
- A shared read must be deliberately named in this ADR or in a later ADR; it
  must not imply shared write access.
- All tenant-scoped access remains subject to tenant filtering and RLS. A
  cross-tenant request for a resource must resolve as `404`, not disclose the
  resource through `403`.

Direct learner-course assignment has additional invariants:

- only active `student` users of the same tenant can be assigned manually;
- direct removal is allowed only for `source='manual'`;
- department-, position-, or cohort-driven assignments are changed through the
  corresponding rule and materialization flow, never by deleting an enrollment;
- tenant admins do not choose individual learner trajectories.

### 5. Frontend policy

The active role drives navigation and direct-route protection.

- Methodologist-only links are not actionable to tenant admins.
- Tenant-administration links are not actionable to methodologists.
- Student navigation is limited to learner surfaces.
- A role switch updates both the active session and visible role-specific UI
  before the target route is used.
- Page-level guards improve UX but never replace backend authorization.
- UI must never expose `teacher` as a selectable, displayed, or fallback role.

## Acceptance criteria for role-matrix changes

### Backend

For every changed role guard or tenant-scoped capability, focused tests must
cover the active roles relevant to that route.

1. The owning active role receives the expected success response.
2. Every non-owning active role receives `403` before the mutation executes.
3. A two-tenant scenario returns `404` for a same-role caller from the other
   tenant.
4. A multi-role account can use each domain only after switching to the
   corresponding active role; a token with an unassigned selected role is
   rejected.
5. Login and refresh preserve the primary/active-role contract, and switching
   a role rotates the session tokens.
6. Legacy route behavior is covered where a redirect or alias is retained.

### Frontend

Role-matrix tests must cover the active session state, not only a mocked
sidebar item.

1. Each active role sees its canonical navigation and does not see actionable
   mutations from the other tenant domain.
2. Switching between assigned `admin`/`org_admin`, `methodologist`, and
   `student` roles changes navigation and lands on the matrix target.
3. Direct entry to a blocked tenant-admin learning route and a tenant-user
   platform route redirects according to this ADR.
4. The legacy redirects resolve to their canonical routes.
5. No role picker, navigation item, or fallback label contains `teacher`.

## Consequences and conformance work

- Product and documentation reviews use this matrix rather than inferring
  ownership from a particular `require_role(...)` call.
- Existing historical multi-role mutation guards must be aligned by the
  responsible backend owner in a separately scoped implementation task; this
  ADR deliberately does not preserve them as policy exceptions.
- A future role or shared write surface requires an ADR amendment and matching
  backend/frontend tests before implementation.

## Cross-references

- [ADR-0003](./0003-multitenant.md): multi-tenancy and tenant isolation
- [ADR-0004](./0004-rls-force-and-app-role.md): RLS and the `lms_app` runtime role
- [ADR-0008](./0008-auth-strategy.md): JWT, refresh-cookie, and active-role session behavior
- [ADR-0011](./0011-users-staff-refactor.md): separation of system-team management, staff structure, and learners
- [PROJECT.md](../../PROJECT.md): current product roles and route ownership
