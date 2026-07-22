# Frontend role policy and auth guard

## Scope

Align the Next.js navigation and client-side route guard with ADR-0012. Only
`apps/web` and this plan are in scope; backend, production, and deployment are
out of scope.

## 1. Create a canonical, typed role and route policy

**Files:** `apps/web/src/lib/rolePolicy.ts`, `Layout.tsx`, `Sidebar.tsx`,
`CommandPalette.tsx`.

**Plan:** Define the allowed navigation surfaces and role home routes in one
pure module. Use it to filter Sidebar and Command Palette actions and to make
the layout redirect users away from disallowed routes.

**Checks:** Focused Vitest role/route matrix.

**What changed:** Added `apps/web/src/lib/rolePolicy.ts` as the typed source of
truth for role homes, allowed client routes, auth redirects, and query-aware
navigation state. `Layout`, `Sidebar`, and `CommandPalette` now consume it.

**Checks:** Added `apps/web/tests/rolePolicy.test.ts`; `npm.cmd test` passed
(65 tests).

**Status:** ✅ done

## 2. Repair auth and navigation regressions

**Files:** `Layout.tsx`, `Sidebar.tsx`, login/registration entry points as
needed.

**Plan:** Make the auth guard react to initialization and token changes,
remove debug logging, prevent pre-user navigation exposure, select the correct
role home, and make the staff navigation active state query-aware.

**Checks:** Focused auth-restore failure regression tests.

**What changed:** The layout now reacts to `initialized` and `accessToken`,
redirecting a failed restore to `/login` without debug logging. Sidebar hides
all items until a user is available, and the staff structure link recognizes
its query string. Shared role homes now send admin and org_admin sessions to
`/admin` after login, registration, invite acceptance, or role switching.

**Checks:** Auth-restore failure and role-home assertions are covered in
`apps/web/tests/rolePolicy.test.ts`; `npm.cmd run typecheck` passed.

**Status:** ✅ done

## 3. Verify the complete frontend change

**Files:** frontend tests and QA evidence path, if present.

**Plan:** Run unit tests, typecheck, production build, desktop/mobile browser
QA, and an accessibility smoke check. Record screenshots only in the
repository's established evidence location.

**Checks:** command output plus browser evidence.

**What changed:** Added the role/route matrix and auth-restore failure regression coverage. Completed desktop and mobile browser smoke checks for the local login flow and accessibility semantics without using credentials.

**Checks:** `npm.cmd test` (65 passing), `npm.cmd run typecheck`, and `npx.cmd next build` all passed. Browser QA at 1280px and 390px found no console errors; the page exposes one main region, a labeled email input, a page heading, and skip links. The production build retains pre-existing lint warnings outside this task's scope.

**Status:** done

## 4. Correct training-log shared read-only access

**Files:** `apps/web/src/lib/rolePolicy.ts`, training-log page, Sidebar, and
`apps/web/tests/rolePolicy.test.ts`.

**Plan:** Restore the ADR-0012 shared training-log route for tenant admin,
org_admin, and methodologist without granting learning-content mutation routes.

**What changed:** Added `/admin/training-log` only to the admin and org_admin
route policies. Sidebar and the training-log fallback gate now use that shared
policy. Student and superadmin access remains denied.

**Checks:** Added explicit role matrix and direct-route redirect assertions.

**Checks:** `npm.cmd test` (75 passing), `npm.cmd run typecheck`, and
`npx.cmd next build` passed. The build retains only pre-existing lint warnings
outside this correction.

**Status:** done
