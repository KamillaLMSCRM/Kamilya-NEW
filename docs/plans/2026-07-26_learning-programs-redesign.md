# Learning programs redesign

Date: 2026-07-26
Owner: Codex
Status: implemented and approved for production release

## Product decision

The methodologist-facing entity is presented as **Программа обучения**.
`learning_path` remains the internal API/database term. A program is not a
public list of tenant courses: it is a versioned, ordered curriculum assigned
to a concrete learner audience.

Tenant administrators do not manage programs. The canonical owner is the
active `methodologist` role.

## Target flow

1. The methodologist creates a draft with a name, purpose and sequencing mode.
2. Published tenant courses are added to a numbered vertical curriculum.
3. Each step is marked required or optional and can be reordered.
4. The program is assigned to learners directly or through cohorts,
   departments and positions, with optional start and due dates.
5. Publication validates that the program has at least one course and at least
   one required course.
6. Learners see only programs assigned to them. In a sequential program, the
   next required step opens after the preceding required step is completed.
7. Published content is immutable. Further curriculum changes create a new
   version; existing learner assignments continue to point at their original
   version.

## Implementation contract

### Backend and database

- Add Alembic revision `0075`.
- Extend `learning_paths` with version-family metadata, sequencing mode and
  publication timestamps.
- Extend curriculum steps so `required` is an editable API field.
- Add tenant-scoped individual `learning_path_assignments` with source,
  audience reference, start/due dates, status and audit metadata.
- Enable and force RLS for every new tenant table and grant only the required
  DML privileges to `lms_app`.
- Manager API:
  - list/detail/create draft;
  - update draft metadata;
  - replace ordered curriculum using structured step items;
  - publish with validation;
  - create a new draft version from a published program;
  - resolve and assign learner audiences;
  - list/cancel assignments.
- Learner API:
  - return only individually assigned published programs;
  - return ordered steps with `locked`, `available` or `completed` state;
  - calculate progress from required steps.
- Assignment/progression service:
  - materialize enrollments only for currently available steps;
  - sync the next step after course completion;
  - preserve direct/rule-driven access when the same course is available from
    another source.
- Keep all manager mutations restricted to `methodologist`.

### Frontend

- Rename the visible section to `Программы обучения`.
- Replace the ambiguous checkbox grid with a builder:
  - available-course search;
  - numbered selected-course sequence;
  - explicit add/remove and move controls;
  - required/optional control.
- Use four explicit stages: `Основное`, `Содержание`, `Аудитория`, `Проверка`.
- Create a draft first; never publish an empty program.
- Show draft/published/archived state, version, learner count and assignment
  status in the list.
- Add audience selectors for learners, cohorts, departments and positions.
- Add a learner program screen with course state, progress and a direct action
  for the currently available course.
- Provide explanatory empty states and disabled-action reasons.
- Keep compact operational styling and verify desktop and mobile layouts.

### Documentation

- Update the Russian user guide and internal project documentation.
- Record the final API/data behavior and explicitly remove the old statement
  that every tenant learner sees every published path.

## Verification

- Alembic upgrade from `0074` and schema/RLS assertions.
- Backend unit and integration tests for tenant isolation, draft/publish
  lifecycle, version immutability, audience resolution, learner visibility and
  sequential release.
- Frontend component tests for draft creation, ordering, publication
  validation, assignment and learner states.
- Full backend test suite.
- Full frontend test suite, TypeScript check and production build.
- Browser QA at desktop and mobile sizes for methodologist and learner roles.
- No push or production deployment until the complete local gate passes.

## Progress

### Step 1 - architecture and current-state audit

**What was found:** The existing page creates a published empty path, discards
course selections made before creation, renders a decorative drag handle
without reordering, exposes all published paths to all tenant learners and has
no audience assignment or sequential access control.

**Checks:** Read the current frontend, learning-path API/models/schemas,
enrollment access policy, student dashboard and course completion flow.

**Status:** done

### Step 2 - backend/data implementation

**What was delivered:** Alembic `0075`, version families, immutable published
curricula, structured required/optional steps, tenant-scoped assignments,
audience resolution, learner visibility and enrollment release after course
completion.

**Status:** done

### Step 3 - frontend implementation

**What was delivered:** four-stage methodologist builder, explicit course
ordering, draft/publish/version flow, audience assignment, assignment history
and learner progress with locked/available/completed steps in RU/EN/KK.

**Status:** done

### Step 4 - documentation

**What was updated:** `PROJECT.md`, internal project documentation and the
Russian user guide now describe the implemented program, assignment and
versioning rules.

**Status:** done

### Step 5 - local and browser verification

**Automated checks:**

- backend: `507 passed`;
- focused program backend tests: `11 passed`;
- frontend: `138 passed`;
- focused program UI tests: `4 passed`;
- TypeScript: passed;
- Next.js production build: passed with pre-existing lint warnings outside
  this feature.

**Browser QA:** passed on an isolated local API/web stack. Verified
methodologist and learner demo authentication, empty states, the basic and
curriculum editor stages at 1440×1000 and 390×844, zero horizontal overflow
and zero browser console errors. Temporary QA processes were stopped.

**Status:** done

### Step 6 - release

**Status:** approved on 2026-07-26; production deployment and smoke verification
are in progress
